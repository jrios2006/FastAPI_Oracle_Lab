#!/usr/bin/env python3
"""F6: monitor Oracle externo para una campaña T06, con exportacion CSV.

Ejemplo desde la raiz del proyecto (terminal A):
    python scripts/run_monitor.py --run-id LAB_T06_20261030_A --duration 45 --interval 0.5 --http-samples 4

No genera carga sobre el pool de API: su unica conexion Oracle pertenece a
LAB_MONITOR y se etiqueta LAB_POOL_MONITOR. Las peticiones opcionales a
/diagnostics/pool NO consultan Oracle; al ser aleatorias por Gunicorn no se
garantiza que cada muestra observe todos los workers.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import oracledb
from module.config_loader import ConfigLoader
from module.oracle_client import OracleClient
from monitoring.metrics_collector import MetricsCollector
from monitoring.oracle_monitor import OracleMonitor
from monitoring.process_monitor import snapshot as process_snapshot

_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def pool_sample(url: str) -> dict:
    try:
        with urlopen(url, timeout=1.25) as reply:
            payload = json.load(reply)
            if not isinstance(payload, dict):
                raise ValueError("Respuesta pool no es JSON objeto")
            return payload
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="F6: monitor externo de sesiones y pools (solo lectura)")
    p.add_argument("--run-id", required=True, help="Identificador comun a monitor y prueba HTTP")
    p.add_argument("--duration", type=float, default=45.0, help="Duracion en segundos (1..900)")
    p.add_argument("--interval", type=float, default=0.5, help="Muestreo objetivo en segundos (0.25..10)")
    p.add_argument("--http-samples", type=int, default=4, help="Solicitudes /diagnostics/pool por muestra (0..16)")
    p.add_argument("--base-url", default="http://127.0.0.1:8010")
    p.add_argument("--out", type=Path, help="Directorio de salida (por defecto reports/sesiones/RUN_ID)")
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if not _RUN_ID.fullmatch(args.run_id):
        parser().error("run-id solo permite 1..64 caracteres alfanumericos, _ o -")
    if not 1 <= args.duration <= 900 or not 0.25 <= args.interval <= 10:
        parser().error("--duration 1..900 y --interval 0.25..10")
    if not 0 <= args.http_samples <= 16:
        parser().error("--http-samples debe estar entre 0 y 16")
    if args.base_url.rstrip("/") != "http://127.0.0.1:8010":
        parser().error("El monitor HTTP solo admite http://127.0.0.1:8010")
    config = ConfigLoader().load(ROOT / "config" / "config.json")
    creds = ConfigLoader().load(ROOT / "config" / "credenciales.json")
    account = creds.get("LAB_MONITOR") if isinstance(creds, dict) else None
    if not isinstance(config, dict) or not isinstance(account, dict):
        print("ERROR: faltan config/config.json o credenciales LAB_MONITOR", file=sys.stderr)
        return 2
    output_dir = args.out or ROOT / "reports" / "sesiones" / args.run_id
    output_dir = output_dir.resolve()
    print(f"[F6] Run ID: {args.run_id} | salida: {output_dir}", flush=True)
    client = None
    try:
        client = OracleClient(
            cfg=account, pool_min=0, pool_max=1, retry=0,
            app_name="FastAPI_Oracle_Lab_MONITOR", user_app="LAB_POOL_MONITOR",
        )
        monitor = OracleMonitor(client)
        # Preflight de permisos: no confundir error de consulta con cero sesiones.
        first = monitor.snapshot()
        with MetricsCollector(output_dir, args.run_id) as collector:
            collector.write_metadata({
                "run_id": args.run_id,
                "fecha_inicio_utc": datetime.now(timezone.utc).isoformat(),
                "duration_s": args.duration, "interval_s": args.interval,
                "http_samples": args.http_samples,
                "oracledb_version": oracledb.__version__,
                "client_version": OracleClient.__version__,
                "monitor_identifier": "LAB_POOL_MONITOR", "api_identifier": "LAB_POOL_API",
                "nota": "Solo muestra observada; no garantiza ver todos los workers por HTTP.",
            })
            start = time.monotonic()
            count, errors = 0, 0
            next_sample = start
            last_print = -999.0
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= args.duration and count > 0:
                    break
                if count == 0:
                    oracle, error = first, None
                else:
                    try:
                        oracle, error = monitor.snapshot(), None
                    except Exception as exc:
                        oracle, error = None, f"{type(exc).__name__}: {str(exc)[:150]}"
                        errors += 1
                try:
                    processes = process_snapshot()
                except Exception:
                    processes = {"masters": [], "workers": []}
                pools = []
                if args.http_samples:
                    url = args.base_url + "/api/v1/lab/diagnostics/pool"
                    with ThreadPoolExecutor(max_workers=args.http_samples) as executor:
                        futures = [executor.submit(pool_sample, url) for _ in range(args.http_samples)]
                        pools = [f.result() for f in as_completed(futures)]
                collector.collect(sample=count, oracle=oracle, error=error,
                                  processes=processes, pool_samples=pools)
                elapsed = time.monotonic() - start
                if elapsed - last_print >= 2 or count == 0:
                    if oracle is None:
                        print(f"[F6] {elapsed:6.1f}s ERROR monitor: {error}", flush=True)
                    else:
                        print(f"[F6] {elapsed:6.1f}s sesiones={oracle['total']} "
                              f"ACTIVE={oracle['active']} INACTIVE={oracle['inactive']} "
                              f"workers_con_sesion={oracle['workers_with_sessions']}", flush=True)
                    last_print = elapsed
                count += 1
                next_sample += args.interval
                pause = next_sample - time.monotonic()
                if pause > 0:
                    time.sleep(pause)
        print(f"[F6] Fin: {count} muestras, errores Oracle={errors}, salida={output_dir}")
        return 0 if errors == 0 else 1
    except Exception as exc:
        print(f"ERROR monitor F6 ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
