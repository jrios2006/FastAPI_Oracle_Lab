"""
FastAPI_Oracle_Lab - gunicorn.conf.py
===================================

F5 - Servidor Gunicorn multiproceso para los ensayos de pools Oracle.

Objetivos:
- Leer host, puerto y numero de workers desde config/config.json.
- Permitir que start_gunicorn.sh ajuste el numero de workers con LAB_WORKERS.
- Mantener la aplicacion SIN precargar en el master (preload_app=False).
- Mantener cada instancia de OracleClient dentro del lifespan de su worker.
- Evitar reinicios automaticos que distorsionen las medidas de conexiones.
- Registrar PID de master y workers para correlacionarlo con Oracle.

Este archivo NO importa main.py, NO importa OracleClient y NO abre Oracle.
La opcion timeout de Gunicorn NO es el timeout de conexiones de Oracle.
"""

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "config.json"

with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
    _settings = json.load(config_file)

_server = _settings.get("servidor")
if not isinstance(_server, dict):
    raise RuntimeError("config/config.json: falta el objeto 'servidor'")

# El laboratorio no incorpora autenticacion: impedir exposicion accidental.
_host = str(_server.get("host", "127.0.0.1"))
if _host != "127.0.0.1":
    raise RuntimeError("Por seguridad, F5 solo admite servidor.host='127.0.0.1'")

try:
    _port = int(_server.get("puerto", 8010))
    _workers = int(os.environ.get("LAB_WORKERS", _server.get("workers", 1)))
except (TypeError, ValueError) as exc:
    raise RuntimeError("Puerto o numero de workers no es un entero valido") from exc

if not 1024 <= _port <= 65535:
    raise RuntimeError("El puerto debe estar entre 1024 y 65535")
if not 1 <= _workers <= 8:
    raise RuntimeError("F5 admite entre 1 y 8 workers, para limitar el consumo Oracle")

# Opciones de Gunicorn. No crear pools en el master ni pasar conexiones por fork.
bind = f"{_host}:{_port}"
workers = _workers
worker_class = "uvicorn_worker.UvicornWorker"
preload_app = False
reload = False
daemon = False
reuse_port = False

# Evitar rotaciones/reinicios automaticos durante ensayos de inactividad.
max_requests = 0
max_requests_jitter = 0

# Tiempos del servidor HTTP (INDEPENDIENTES de pool.timeout=60 de Oracle).
timeout = 120
graceful_timeout = 30
keepalive = 5

# Gunicorn informa de master y workers por stderr/stdout. Los mensajes de
# aplicacion se guardan ademas en logs/app.pid-<PID>.log (utils/logger.py).
errorlog = "-"
accesslog = "-"
loglevel = "info"
access_log_format = '%(h)s %(t)s "%(r)s" %(s)s %(b)s'
capture_output = False

# Facilita el seguimiento de procesos, sin crear sesiones Oracle.
proc_name = "FastAPI_Oracle_Lab"


def on_starting(server):
    """Identifica al master sin ejecutar codigo de la aplicacion."""
    server.log.info("LAB GUNICORN MASTER START | pid=%s bind=%s workers=%s preload=%s",
                    os.getpid(), bind, workers, preload_app)


def post_fork(server, worker):
    """Identifica el worker; el pool se creara despues, en lifespan."""
    server.log.info("LAB GUNICORN WORKER FORK | pid=%s master_pid=%s",
                    worker.pid, os.getppid())


def worker_exit(server, worker):
    """La limpieza Oracle se realiza en main.lifespan, no en este hook."""
    server.log.info("LAB GUNICORN WORKER EXIT | pid=%s", worker.pid)


def on_exit(server):
    """Registra la salida del master Gunicorn."""
    server.log.info("LAB GUNICORN MASTER EXIT | pid=%s", os.getpid())
