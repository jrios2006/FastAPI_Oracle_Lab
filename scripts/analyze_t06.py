#!/usr/bin/env python3
"""Analiza los resultados de una campaña T06, sin Oracle ni HTTP.

Consume CSV del monitor F6 y summary.json del generador de carga.
No inventa mediciones para workers omitidos por el muestreo HTTP.
No infiere que un pico de solicitudes HTTP sea ocupacion Oracle.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"No existe {path}")
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def maybe_int(value, fallback=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def analyze(run_id: str, monitor_dir: Path, load_dir: Path, pool_max: int) -> dict:
    totals = read_csv(monitor_dir / "oracle_totals.csv")
    sessions = read_csv(monitor_dir / "oracle_sessions.csv")
    pools = read_csv(monitor_dir / "pool_samples.csv")
    summary = json.loads((load_dir / "summary.json").read_text(encoding="utf-8"))
    if summary.get("run_id") != run_id:
        raise ValueError("El run_id de carga no coincide con la campana")
    valid = [row for row in totals if row.get("status") == "OK"]
    oracle_errors = len(totals) - len(valid)
    if not valid:
        raise ValueError("El monitor no produjo muestras Oracle validas")
    peak_total = max(maybe_int(r.get("total"), 0) for r in valid)
    peak_active = max(maybe_int(r.get("active"), 0) for r in valid)
    peak_inactive = max(maybe_int(r.get("inactive"), 0) for r in valid)
    last_total = maybe_int(valid[-1].get("total"), None)
    per_worker_sample = defaultdict(int)
    for row in sessions:
        pid = row.get("worker_pid", "").strip()
        sample = row.get("sample", "").strip()
        if pid and sample:
            per_worker_sample[(pid, sample)] += 1
    peak_by_pid = {}
    for (pid, _), count in per_worker_sample.items():
        peak_by_pid[pid] = max(peak_by_pid.get(pid, 0), count)
    valid_pools = [p for p in pools if maybe_int(p.get("opened")) is not None]
    observed_pool_pids = {p["worker_pid"] for p in valid_pools if p.get("worker_pid")}
    peak_opened = max((maybe_int(p.get("opened"), 0) for p in valid_pools), default=None)
    peak_busy = max((maybe_int(p.get("busy"), 0) for p in valid_pools), default=None)
    violations = [
        {"pid": p.get("worker_pid"), "opened": p.get("opened"), "busy": p.get("busy")}
        for p in valid_pools
        if maybe_int(p.get("opened"), 0) > pool_max or
           maybe_int(p.get("busy"), 0) > pool_max or
           maybe_int(p.get("busy"), 0) > maybe_int(p.get("opened"), 0)
    ]
    worker_session_violations = {pid: n for pid, n in peak_by_pid.items() if n > pool_max}
    ok_http = summary.get("failed", 1) == 0
    active_concurrent = peak_active >= 2
    baseline_returned = last_total == 0  # Solo evidencia puntual de la ultima muestra.
    status = (
        "APTO_PRELIMINAR" if ok_http and oracle_errors == 0 and active_concurrent
        and baseline_returned and not violations and not worker_session_violations
        else "INCONCLUSO_O_REVISAR"
    )
    return {
        "run_id": run_id, "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "http": summary,
        "oracle": {
            "samples_ok": len(valid), "samples_error": oracle_errors,
            "peak_total_sessions": peak_total,
            "peak_active_sessions": peak_active,
            "peak_inactive_sessions": peak_inactive,
            "last_valid_sample_sessions": last_total,
            "max_sessions_by_pid": dict(sorted(peak_by_pid.items())),
            "oracle_concurrent_observed": active_concurrent,
        },
        "pools_http": {
            "workers_observed": len(observed_pool_pids),
            "peak_opened_observed": peak_opened,
            "peak_busy_observed": peak_busy,
            "pool_max_configured_per_worker": pool_max,
            "violations": violations,
            "per_worker_oracle_session_violations": worker_session_violations,
        },
        "caveats": [
            "APTO_PRELIMINAR solo valida las muestras de esta campana; no certifica estabilidad prolongada.",
            "La ultima muestra con 0 sesiones no garantiza ausencia de sesiones futuras.",
            "Los workers que no respondieron /diagnostics/pool pueden quedar sin medir en opened/busy.",
            "La concurrencia HTTP y Oracle pueden diferir; Oracle ACTIVE es una muestra puntual.",
            "DBMS_SESSION.SLEEP no reproduce la carga de consultas/servicios reales.",
        ],
    }


def render_report(data: dict) -> str:
    h, o, p = data["http"], data["oracle"], data["pools_http"]
    rows = [
        f"# Informe F6/F7 T06 — {data['run_id']}", "",
        f"**Indicador preliminar:** `{data['status']}`", "",
        "## Generador HTTP", "",
        f"- Solicitudes: {h.get('successful')}/{h.get('requests')} correctas; "
        f"concurrencia configurada: {h.get('concurrency_http')}; espera Oracle: {h.get('oracle_sleep_seconds')} s.",
        f"- Duracion del escenario: {h.get('wall_seconds')} s; p95 HTTP: {h.get('http_p95_ms')} ms.",
        f"- Mayor espera por adquisicion del pool reportada: {h.get('max_reported_pool_wait_ms')} ms.",
        f"- Respuestas por PID: `{h.get('requests_by_pid')}`.", "",
        "## Monitor Oracle externo", "",
        f"- Muestras validas: {o['samples_ok']}; errores de muestreo: {o['samples_error']}.",
        f"- Pico sesiones totales: **{o['peak_total_sessions']}**; "
        f"pico ACTIVE: **{o['peak_active_sessions']}**; "
        f"pico INACTIVE: {o['peak_inactive_sessions']}.",
        f"- Sesiones en ultima muestra valida: **{o['last_valid_sample_sessions']}**.",
        f"- Pico por PID (sesiones fisicas): `{o['max_sessions_by_pid']}`.",
        "", "## Diagnosticos HTTP de pools", "",
        f"- Workers muestreados al menos una vez: {p['workers_observed']}.",
        f"- Pico `opened` observado: **{p['peak_opened_observed']}**; "
        f"pico `busy` observado: **{p['peak_busy_observed']}**; "
        f"`pool_max` configurado: {p['pool_max_configured_per_worker']}.",
        f"- Infracciones observadas de limite: {len(p['violations'])}; "
        f"infracciones de sesiones por worker: {len(p['per_worker_oracle_session_violations'])}.",
        "", "## Limitaciones", "",
    ]
    rows += [f"- {note}" for note in data["caveats"]]
    rows.append("")
    return "\n".join(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analizar T06 a partir de los CSV/JSON")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--monitor-dir", type=Path)
    parser.add_argument("--load-dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.run_id):
        parser.error("run-id invalido")
    monitor_dir = args.monitor_dir or ROOT / "reports" / "sesiones" / args.run_id
    load_dir = args.load_dir or ROOT / "reports" / "rendimiento" / args.run_id
    output_dir = args.out or ROOT / "reports" / "resultados" / args.run_id
    config = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    pool_max = int(config.get("oracle", {}).get("pool_max", 5))
    data = analyze(args.run_id, monitor_dir, load_dir, pool_max)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(render_report(data), encoding="utf-8")
    print(f"[T06] {data['status']} | sesiones max={data['oracle']['peak_total_sessions']} "
          f"ACTIVE max={data['oracle']['peak_active_sessions']} "
          f"busy observado max={data['pools_http']['peak_busy_observed']}")
    print(f"[T06] Informes: {output_dir / 'report.md'} y {output_dir / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
