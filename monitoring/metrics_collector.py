"""Exportacion incremental de muestras externas a CSV, sin credenciales.

Se escriben cero sesiones mediante una fila TOTAL en cada intervalo,
para diferenciar de un monitor detenido. Errores son muestras ERROR, NUNCA 0.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class MetricsCollector:
    def __init__(self, directory: Path, run_id: str):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self._files = []
        self._writers = {}
        specs = {
            "oracle_totals": ("oracle_totals.csv", ["timestamp_utc", "run_id", "sample", "status", "total", "active", "inactive", "workers_with_sessions", "error"]),
            "oracle_sessions": ("oracle_sessions.csv", ["timestamp_utc", "run_id", "sample", "worker_pid", "sid", "serial#", "status", "last_call_et", "logon_time", "client_info"]),
            "processes": ("processes.csv", ["timestamp_utc", "run_id", "sample", "master_pids", "worker_pids", "count_workers"]),
            "pool_samples": ("pool_samples.csv", ["timestamp_utc", "run_id", "sample", "worker_pid", "pool_identity", "opened", "busy", "max", "ciclo_de_vida", "error"]),
        }
        for key, (name, fields) in specs.items():
            out = (directory / name).open("w", newline="", encoding="utf-8")
            self._files.append(out)
            writer = csv.DictWriter(out, fieldnames=fields)
            writer.writeheader()
            self._writers[key] = writer

    def collect(self, *, sample: int, oracle: dict | None, error: str | None,
                processes: dict, pool_samples: list[dict]):
        ts = utc_now()
        base = {"timestamp_utc": ts, "run_id": self.run_id, "sample": sample}
        if oracle is None:
            self._writers["oracle_totals"].writerow({**base, "status": "ERROR", "error": error})
        else:
            self._writers["oracle_totals"].writerow({
                **base, "status": "OK", "total": oracle["total"],
                "active": oracle["active"], "inactive": oracle["inactive"],
                "workers_with_sessions": oracle["workers_with_sessions"],
            })
            for session in oracle["sessions"]:
                self._writers["oracle_sessions"].writerow({
                    **base, "worker_pid": session.get("worker_pid"),
                    "sid": session.get("sid"), "serial#": session.get("serial#"),
                    "status": session.get("status"), "last_call_et": session.get("last_call_et"),
                    "logon_time": session.get("logon_time"), "client_info": session.get("client_info"),
                })
        self._writers["processes"].writerow({
            **base, "master_pids": ";".join(map(str, processes.get("masters", []))),
            "worker_pids": ";".join(map(str, processes.get("workers", []))),
            "count_workers": len(processes.get("workers", [])),
        })
        for pool in pool_samples:
            self._writers["pool_samples"].writerow({
                **base,
                "worker_pid": pool.get("pid"),
                "pool_identity": pool.get("pool_identity"),
                "opened": pool.get("opened"), "busy": pool.get("busy"),
                "max": pool.get("max"), "ciclo_de_vida": pool.get("ciclo_de_vida"),
                "error": pool.get("error"),
            })
        for file in self._files:
            file.flush()

    def write_metadata(self, data: dict):
        (self.directory / "monitor_meta.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )

    def close(self):
        for file in self._files:
            file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
