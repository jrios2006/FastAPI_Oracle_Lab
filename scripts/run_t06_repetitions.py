#!/usr/bin/env python3
"""Ejecutor secuencial de repeticiones T06 (F5/F6/F7).

Gestiona *solo* el Gunicorn que arranca este proceso. No se adjunta a un
servidor preexistente ni detiene procesos ajenos. Nunca importa OracleClient
ni altera el API, el driver o los pool_config existentes.

Ejecucion desde raiz del proyecto, con el entorno virtual instalado:
    python scripts/run_t06_repetitions.py --dry-run
    python scripts/run_t06_repetitions.py --workers 2,4,8 --repeats 3

Orden por escenario: iniciar Gunicorn -> esperar workers y /health ->
monitor Oracle -> comprobar primera muestra OK -> carga HTTP -> esperar
monitor completo -> analizar -> registrar metadata -> repetir.
El puerto 127.0.0.1:8010 debe estar libre al iniciar.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
API_HOST, API_PORT = "127.0.0.1", 8010


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_workers(value: str) -> list[int]:
    try:
        workers = [int(x.strip()) for x in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("workers: usar 2,4,8") from exc
    if not workers or any(not 1 <= w <= 8 for w in workers) or len(set(workers)) != len(workers):
        raise argparse.ArgumentTypeError("workers: lista unica de valores 1..8")
    return workers


def args_parser():
    p = argparse.ArgumentParser(description="T06: automatizar series con Gunicorn, monitor y carga")
    p.add_argument("--workers", type=parse_workers, default=[2, 4, 8], help="Lista: 2,4,8")
    p.add_argument("--repeats", type=int, default=3, help="Repeticiones por escenario (1..10)")
    p.add_argument("--concurrency", type=int, default=12, help="HTTP concurrentes (1..16)")
    p.add_argument("--requests", type=int, default=24, help="Solicitudes por repeticion (>= concurrency, <=320)")
    p.add_argument("--seconds", type=float, default=3.0, help="DBMS_SESSION.SLEEP por peticion (0.1..5)")
    p.add_argument("--monitor-duration", type=float, default=240.0, help="Monitor por repeticion (30..900 s)")
    p.add_argument("--monitor-interval", type=float, default=1.0, help="Muestreo del monitor (0.25..10 s)")
    p.add_argument("--http-samples", type=int, default=8, help="Consultas de /diagnostics/pool por muestra (0..16)")
    p.add_argument("--prefix", default=f"LAB_T06_R_{datetime.now().strftime('%Y%m%d')}",
                   help="Prefijo comun para run_ids nuevos (sin espacios)")
    p.add_argument("--startup-timeout", type=float, default=50.0, help="Espera al arrancar Gunicorn (s)")
    p.add_argument("--cooldown", type=float, default=3.0, help="Pausa entre repeticiones (s)")
    p.add_argument("--dry-run", action="store_true", help="Mostrar plan SIN arrancar servicios")
    return p


def check_arguments(p, args):
    if not 1 <= args.repeats <= 10:
        p.error("--repeats: 1..10")
    if not 1 <= args.concurrency <= 16 or not args.concurrency <= args.requests <= 320:
        p.error("--concurrency: 1..16 y --requests: concurrency..320")
    if not 0.1 <= args.seconds <= 5.0:
        p.error("--seconds: 0.1..5")
    if not 30 <= args.monitor_duration <= 900:
        p.error("--monitor-duration: 30..900")
    if not 0.25 <= args.monitor_interval <= 10 or not 0 <= args.http_samples <= 16:
        p.error("--monitor-interval: 0.25..10, --http-samples: 0..16")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", args.prefix):
        p.error("--prefix: solo 1..48 caracteres alfanumericos, _ o -")
    if not 5 <= args.startup_timeout <= 120 or args.cooldown < 0:
        p.error("--startup-timeout 5..120 y --cooldown >= 0")
    runs = [(w, repeat, f"{args.prefix}_W{w}_R{repeat:02d}")
            for w in args.workers for repeat in range(1, args.repeats + 1)]
    if any(len(run_id) > 64 for _, _, run_id in runs):
        p.error("run_id excede 64 caracteres: usar prefijo mas corto")
    return runs


def port_occupied():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((API_HOST, API_PORT)) == 0


def worker_children(master_pid: int) -> list[int]:
    try:
        output = subprocess.run(["ps", "-eo", "pid=,ppid="], check=True,
                                capture_output=True, text=True, timeout=5).stdout
        return [int(columns[0]) for line in output.splitlines()
                if len(columns := line.split()) == 2 and int(columns[1]) == master_pid]
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def health_ok():
    try:
        with urlopen(f"http://{API_HOST}:{API_PORT}/api/v1/lab/health", timeout=1.5) as reply:
            payload = json.load(reply)
            return reply.status == 200 and payload.get("success") is True
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return False


def tail(path: Path, max_lines: int = 18):
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:])
    except OSError:
        return "(no disponible)"


def wait_for_server(process: subprocess.Popen, workers: int, seconds: float, log: Path):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Gunicorn finalizo al arrancar (rc={process.returncode}):\n{tail(log)}")
        if len(worker_children(process.pid)) == workers and health_ok():
            print(f"[AUTO] Gunicorn listo: master={process.pid}, workers={workers}", flush=True)
            return
        time.sleep(0.5)
    raise RuntimeError(f"Gunicorn no quedo listo en {seconds}s. Log:\n{tail(log)}")


def launch(command, log_path: Path, *, process_group=False):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = log_path.open("w", encoding="utf-8")
    try:
        proc = subprocess.Popen(command, cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, start_new_session=process_group)
    except BaseException:
        stream.close()
        raise
    # El hijo conserva el descriptor; el padre ya no lo necesita.
    stream.close()
    return proc


def stop_child(process: subprocess.Popen | None, *, group: bool):
    if process is None or process.poll() is not None:
        return
    try:
        if group:
            os.killpg(process.pid, signal.SIGINT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=40 if group else 8)
    except (ProcessLookupError, OSError):
        pass
    except subprocess.TimeoutExpired:
        # Solo el grupo que creamos; no matar servicios ajenos.
        try:
            if group:
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=8)
        except (ProcessLookupError, subprocess.TimeoutExpired, OSError):
            if process.poll() is None:
                if group:
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait(timeout=5)


def monitor_first_sample_ok(path: Path):
    """False hasta que se haya escrito una fila OK real."""
    if not path.exists():
        return False
    try:
        with path.open(newline="", encoding="utf-8") as f:
            rows = csv.DictReader(f)
            row = next(rows, None)
            return row is not None and row.get("status") == "OK"
    except (OSError, UnicodeError, csv.Error):
        return False


def wait_for_monitor(process: subprocess.Popen, run_id: str, log: Path, seconds=35):
    first = ROOT / "reports" / "sesiones" / run_id / "oracle_totals.csv"
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Monitor termino durante preflight ({run_id}):\n{tail(log)}")
        if monitor_first_sample_ok(first):
            return
        time.sleep(0.25)
    raise RuntimeError(f"Sin primera muestra Oracle valida para {run_id}:\n{tail(log)}")


def run_logged(command, log_path: Path, timeout: float):
    proc = launch(command, log_path)
    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stop_child(proc, group=False)
        raise RuntimeError(f"Tiempo agotado: {' '.join(map(str, command))}\n{tail(log_path)}") from exc
    if rc != 0:
        raise RuntimeError(f"Proceso salio con codigo {rc}: {' '.join(map(str, command))}\n{tail(log_path)}")


def wait_full_monitor(monitor: subprocess.Popen, duration: float, log: Path):
    # El monitor ya habia iniciado la cuenta cuando escribio su primera fila.
    deadline = time.monotonic() + duration + 80
    last_update = 0.0
    while monitor.poll() is None:
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Monitor supera duracion prevista: {log}\n{tail(log)}")
        if time.monotonic() - last_update >= 25:
            print("[AUTO] Monitorizando reposo Oracle...", flush=True)
            last_update = time.monotonic()
        time.sleep(1.0)
    if monitor.returncode != 0:
        raise RuntimeError(f"Monitor termino con error {monitor.returncode}:\n{tail(log)}")


def run_one(py: Path, args, workers: int, repeat: int, run_id: str, logs_dir: Path):
    print(f"\n[AUTO] ==== {run_id}: workers={workers} repeticion={repeat} ====", flush=True)
    meta_path = ROOT / "reports" / "resultados" / run_id / "campaign.json"
    meta_path.parent.mkdir(parents=True, exist_ok=False)
    metadata = {
        "run_id": run_id, "workers": workers, "repeat": repeat,
        "concurrency": args.concurrency, "requests": args.requests,
        "oracle_sleep_seconds": args.seconds,
        "monitor_duration_seconds": args.monitor_duration,
        "monitor_interval_seconds": args.monitor_interval,
        "http_samples": args.http_samples, "start_utc": utc_now(),
        "orchestrator": "scripts/run_t06_repetitions.py", "status": "INICIADA",
    }
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    monitor = None
    try:
        monitor_cmd = [str(py), "scripts/run_monitor.py", "--run-id", run_id,
                       "--duration", str(args.monitor_duration), "--interval", str(args.monitor_interval),
                       "--http-samples", str(args.http_samples)]
        mon_log = logs_dir / run_id / "monitor.log"
        monitor = launch(monitor_cmd, mon_log)
        wait_for_monitor(monitor, run_id, mon_log)
        # Breve margen para una primera muestra de reposo antes de iniciar la carga.
        time.sleep(max(1.0, args.monitor_interval))
        load_cmd = [str(py), "tests/test_concurrency.py", "--run-id", run_id,
                    "--concurrency", str(args.concurrency), "--requests", str(args.requests),
                    "--seconds", str(args.seconds)]
        # 24 peticiones de 3 s con concurrencia 12 ~ 6 s; limite conservador.
        load_timeout = max(100.0, (args.requests / args.concurrency) * (args.seconds + 45))
        run_logged(load_cmd, logs_dir / run_id / "carga.log", timeout=load_timeout)
        print(f"[AUTO] Carga terminada; esperando monitor completo ({args.monitor_duration}s).", flush=True)
        wait_full_monitor(monitor, args.monitor_duration, mon_log)
        analyze_cmd = [str(py), "scripts/analyze_t06.py", "--run-id", run_id]
        run_logged(analyze_cmd, logs_dir / run_id / "analisis.log", timeout=40)
        report = json.loads((ROOT / "reports" / "resultados" / run_id / "report.json").read_text(encoding="utf-8"))
        if report.get("run_id") != run_id:
            raise RuntimeError("El informe no corresponde con el run_id")
        # Version de driver registrada por el monitor real, no inferida de PID.
        monitor_meta_path = ROOT / "reports" / "sesiones" / run_id / "monitor_meta.json"
        monitor_meta = json.loads(monitor_meta_path.read_text(encoding="utf-8"))
        metadata.update({
            "driver_version": monitor_meta.get("oracledb_version", "DESCONOCIDO"),
            "oracle_client_version": monitor_meta.get("client_version", "DESCONOCIDO"),
            "status": report.get("status"), "end_utc": utc_now(),
            "monitor_samples": report["oracle"].get("samples_ok"),
            "last_valid_sample_sessions": report["oracle"].get("last_valid_sample_sessions"),
            "http_successful": report["http"].get("successful"),
            "http_failed": report["http"].get("failed"),
        })
        if metadata["status"] != "APTO_PRELIMINAR":
            raise RuntimeError("Analizador no dio APTO_PRELIMINAR; revisar antes de seguir")
        if report["oracle"].get("samples_error", -1) != 0:
            raise RuntimeError("Existen errores en el monitor Oracle")
        if metadata["last_valid_sample_sessions"] != 0:
            raise RuntimeError("La campana termino con sesiones Oracle abiertas")
        print(f"[AUTO] APTO_PRELIMINAR: sesiones pico={report['oracle']['peak_total_sessions']}, "
              f"ultimo={metadata['last_valid_sample_sessions']}, "
              f"P95={report['http'].get('http_p95_ms')}ms", flush=True)
    except BaseException as exc:
        metadata["status"] = "INTERRUMPIDA" if isinstance(exc, KeyboardInterrupt) else "ERROR_AUTOMATIZACION"
        metadata["end_utc"] = utc_now()
        metadata["error"] = str(exc)[:300]
        raise
    finally:
        stop_child(monitor, group=False)
        meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = args_parser()
    args = parser.parse_args(argv)
    runs = check_arguments(parser, args)
    total_seconds = len(runs) * (args.monitor_duration + args.cooldown)
    print(f"[AUTO] Plan: {len(runs)} campañas, {args.monitor_duration:g}s por monitor; "
          f"duracion minima nominal ~{total_seconds/60:.1f}min + arranques/cierres.")
    for w, repeat, run_id in runs:
        print(f"    {run_id}: workers={w}, concur={args.concurrency}, "
              f"requests={args.requests}, sleep={args.seconds}s")
    if args.dry_run:
        print("[AUTO] DRY-RUN: no se ha iniciado Gunicorn, Oracle ni el generador de carga.")
        return 0

    py = ROOT / ".venv" / "bin" / "python"
    needed = [ROOT / "scripts" / "start_gunicorn.sh", ROOT / "scripts" / "run_monitor.py",
              ROOT / "scripts" / "analyze_t06.py", ROOT / "scripts" / "consolidate_t06.py",
              ROOT / "tests" / "test_concurrency.py", ROOT / "config" / "config.json",
              ROOT / "config" / "credenciales.json", py]
    missing = [str(path) for path in needed if not path.is_file()]
    if missing:
        parser.error("Faltan archivos necesarios: " + ", ".join(missing))
    if port_occupied():
        parser.error("El puerto 127.0.0.1:8010 ya esta ocupado. Deten Gunicorn/Uvicorn antes de comenzar.")
    conflicting = [name for _, _, name in runs if any((ROOT / "reports" / category / name).exists()
                   for category in ("sesiones", "rendimiento", "resultados"))]
    if conflicting:
        parser.error("Existen resultados para run_id; no se sobrescriben: " + ", ".join(conflicting))
    log_root = ROOT / "reports" / "automatizacion" / args.prefix
    if log_root.exists():
        parser.error(f"La carpeta de logs ya existe; usa otro --prefix: {log_root}")
    log_root.mkdir(parents=True)
    completed = 0
    try:
        for workers in args.workers:
            print(f"\n[AUTO] Arrancando Gunicorn con {workers} workers...", flush=True)
            if port_occupied():
                raise RuntimeError("Puerto 8010 ocupado antes de iniciar un nuevo escenario")
            gunicorn_log = log_root / f"gunicorn_W{workers}.log"
            gunicorn = launch(["bash", "scripts/start_gunicorn.sh", str(workers)],
                              gunicorn_log, process_group=True)
            try:
                wait_for_server(gunicorn, workers, args.startup_timeout, gunicorn_log)
                for w, repeat, run_id in runs:
                    if w != workers:
                        continue
                    if gunicorn.poll() is not None:
                        raise RuntimeError(f"Gunicorn termino inesperadamente: {tail(gunicorn_log)}")
                    run_one(py, args, workers, repeat, run_id, log_root)
                    completed += 1
                    if completed < len(runs) and args.cooldown > 0:
                        time.sleep(args.cooldown)
            finally:
                print(f"[AUTO] Cerrando Gunicorn propio (master={gunicorn.pid})...", flush=True)
                stop_child(gunicorn, group=True)
                print(f"[AUTO] Master finalizado, log: {gunicorn_log}", flush=True)

        command = [str(py), "scripts/consolidate_t06.py"]
        run_logged(command, log_root / "consolidacion.log", timeout=40)
        print(f"\n[AUTO] COMPLETADAS: {completed}/{len(runs)} campañas. "
              "Informe: reports/consolidado/T06/informe_consolidado.md")
        return 0
    except KeyboardInterrupt:
        print("\n[AUTO] Interrumpido: se cierran solo los procesos iniciados por este programa.", file=sys.stderr)
        return 130
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"\n[AUTO] ERROR: {exc}\n[AUTO] Campañas completas: {completed}/{len(runs)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
