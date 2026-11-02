#!/usr/bin/env python3
"""T06: genera carga HTTP concurrente, con resultados reproducibles.

No requiere acceso directo a Oracle: todas las llamadas pasan por FastAPI.
No instala paquetes extra (urllib + concurrent.futures son estandar).

Ejemplo desde raiz (terminal B, con monitor externo en terminal A):
  python tests/test_concurrency.py --run-id LAB_T06_20261030_A --concurrency 4 --requests 12 --seconds 3

LIMITES DE SEGURIDAD:
* maximo 16 solicitudes simultaneas; no intenta alcanzar 40 al inicio;
* DBMS_SESSION.SLEEP limitado por API a cinco segundos;
* solo localhost; no modifica datos Oracle.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
URL = "http://127.0.0.1:8010/api/v1/lab/concurrency/hold"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def run_request(index: int, run_id: str, seconds: float, barrier: threading.Barrier | None) -> dict:
    # La barrera sincroniza SOLO la primera oleada, no todas las peticiones.
    if barrier is not None:
        try:
            barrier.wait(timeout=10)
        except threading.BrokenBarrierError:
            pass
    started = time.monotonic()
    result = {
        "index": index, "run_id": run_id,
        "inicio_utc": utc_now(),
        "http_status": 0, "success": False, "pid": "", "error": "",
        "espera_pool_ms": "", "oracle_ms": "", "api_ms": "",
    }
    payload = json.dumps({"run_id": run_id, "segundos": seconds}).encode("utf-8")
    req = Request(URL, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=45) as reply:
            result["http_status"] = reply.status
            data = json.load(reply)
            result["pid"] = data.get("pid", reply.headers.get("X-Lab-Worker-PID", ""))
            result["success"] = (reply.status == 200 and data.get("success") is True)
            result["espera_pool_ms"] = data.get("espera_pool_ms", "")
            result["oracle_ms"] = data.get("duracion_operacion_oracle_ms", "")
            result["api_ms"] = data.get("duracion_total_ms", "")
            if not result["success"]:
                result["error"] = str(data.get("detail", "success=false"))[:150]
    except HTTPError as exc:
        result["http_status"] = exc.code
        # Solo detalles controlados por la API, no volcar errores de red completos.
        result["error"] = f"HTTP {exc.code}: {exc.read(400).decode('utf-8', errors='replace')[:150]}"
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
    result["fin_utc"] = utc_now()
    result["duracion_http_ms"] = round((time.monotonic() - started) * 1000, 2)
    return result


def parser():
    p = argparse.ArgumentParser(description="T06: carga HTTP concurrente controlada")
    p.add_argument("--run-id", required=True, help="Mismo identificador que el monitor F6")
    p.add_argument("--concurrency", type=int, default=4, help="Solicitudes a la vez (1..16)")
    p.add_argument("--requests", type=int, default=12, help="Numero total (1..320)")
    p.add_argument("--seconds", type=float, default=3.0, help="DBMS_SESSION.SLEEP (0.1..5)")
    p.add_argument("--out", type=Path, help="Directorio resultados (por defecto reports/rendimiento/RUN_ID)")
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if not _RUN_ID.fullmatch(args.run_id):
        parser().error("run-id invalido; 1..64 caracteres alfanumericos, _ o -")
    if not 1 <= args.concurrency <= 16 or not 1 <= args.requests <= 320:
        parser().error("concurrency 1..16, requests 1..320")
    if args.requests < args.concurrency:
        parser().error("requests debe ser >= concurrency")
    if not 0.1 <= args.seconds <= 5.0:
        parser().error("seconds 0.1..5.0")
    directory = (args.out or ROOT / "reports" / "rendimiento" / args.run_id).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    print(f"[T06] run_id={args.run_id} concurrencia={args.concurrency} "
          f"requests={args.requests} segundos={args.seconds}", flush=True)
    print(f"[T06] destino={URL} | salida={directory}", flush=True)
    barrier = threading.Barrier(args.concurrency)
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(run_request, i, args.run_id, args.seconds,
                                   barrier if i <= args.concurrency else None)
                   for i in range(1, args.requests + 1)]
        results = [future.result() for future in as_completed(futures)]
    elapsed = time.monotonic() - start
    results.sort(key=lambda r: r["index"])
    columns = ["index", "run_id", "inicio_utc", "fin_utc", "http_status", "success",
               "pid", "duracion_http_ms", "espera_pool_ms", "oracle_ms", "api_ms", "error"]
    with (directory / "requests.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(results)
    ok = sum(row["success"] for row in results)
    by_pid = Counter(str(r["pid"]) for r in results if r["success"])
    latencies = sorted(r["duracion_http_ms"] for r in results)
    p95 = latencies[max(0, int(len(latencies) * .95 + .999) - 1)]
    waits = [float(r["espera_pool_ms"]) for r in results if r["success"] and r["espera_pool_ms"] is not None]
    summary = {
        "run_id": args.run_id, "started_utc": results[0]["inicio_utc"],
        "completed_utc": utc_now(), "requests": args.requests,
        "concurrency_http": args.concurrency, "oracle_sleep_seconds": args.seconds,
        "successful": ok, "failed": args.requests - ok,
        "wall_seconds": round(elapsed, 3),
        "http_p95_ms": p95,
        "max_reported_pool_wait_ms": max(waits) if waits else None,
        "requests_by_pid": dict(sorted(by_pid.items())),
        "nota": "Concurrencia HTTP != conexiones busy; correlacionar con oracle_totals.csv y pool_samples.csv",
    }
    (directory / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[T06] OK={ok}/{args.requests} errores={args.requests-ok} "
          f"wall={elapsed:.2f}s p95={p95:.1f}ms", flush=True)
    print("[T06] Peticiones atendidas por PID:", dict(sorted(by_pid.items())), flush=True)
    print(f"[T06] CSV={directory / 'requests.csv'}", flush=True)
    return 0 if ok == args.requests else 1


if __name__ == "__main__":
    raise SystemExit(main())
