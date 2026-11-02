"""Deteccion NO intrusiva de los procesos Gunicorn del laboratorio.

Utiliza ``ps`` del sistema Linux. No abre Oracle ni hace peticiones HTTP.
La deteccion incluye el nombre/ruta especificos de FastAPI_Oracle_Lab.
"""
from __future__ import annotations

import subprocess


def snapshot() -> dict:
    proc = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,args="],
        text=True, capture_output=True, check=True, timeout=5,
    )
    rows = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        pid, ppid, cmd = parts
        if "FastAPI_Oracle_Lab/gunicorn.conf.py" not in cmd or "-m gunicorn" not in cmd:
            continue
        try:
            rows.append({"pid": int(pid), "ppid": int(ppid)})
        except ValueError:
            continue
    pids = {r["pid"] for r in rows}
    masters = [r["pid"] for r in rows if r["ppid"] not in pids]
    workers = [r["pid"] for r in rows if r["ppid"] in pids]
    return {"masters": sorted(masters), "workers": sorted(workers), "process_count": len(rows)}
