"""
utils.logger
============

Configuracion centralizada de logging con soporte para rotacion automatica
(RotatingFileHandler). Disenado para entornos de produccion donde se requiere
persistencia sin saturar el almacenamiento.

Origen: logger.py v1.2.0 del Backend_Oracle (2026-05-11).
Adaptacion: FastAPI_Oracle_Lab, para medir pools por proceso worker.

Cambios respecto al original:
-----------------------------
1. Incluye UTC y PID en todos los mensajes del laboratorio.
2. Cada worker escribe en su propio archivo para evitar rotacion simultanea
   del mismo archivo por varios procesos Gunicorn.
3. Respeta los handlers ya existentes (incluidos los configurados por el
   servidor) y no silencia uvicorn.access ni uvicorn.error.
4. get_logger() hereda el nivel del logger raiz; ya no fuerza DEBUG para
   cada modulo. La interfaz publica original sigue siendo compatible.
5. setup_logger() es idempotente para los handlers que gestiona; en caso de
   fork limpia los handlers heredados del proceso padre.

Librerias necesarias:
---------------------
- logging (Libreria estandar de Python)
- os (Libreria estandar de Python)
- time (Libreria estandar de Python)
"""

import logging
import os
import time
from pathlib import Path
from logging.handlers import RotatingFileHandler


class _UTCFormatter(logging.Formatter):
    """Muestra una marca temporal UTC para comparar con Oracle y los informes."""

    converter = time.gmtime


def _ruta_por_proceso(log_file: str) -> Path:
    """Evita que varios workers roten simultaneamente un mismo fichero."""
    ruta = Path(log_file)
    return ruta.with_name(f"{ruta.stem}.pid-{os.getpid()}{ruta.suffix}")


def setup_logger(
    log_file: str = "logs/app.log",
    max_bytes: int = 5242880,
    backup_count: int = 5,
    *,
    level: int = logging.INFO,
    console: bool = True,
) -> None:
    """
    Configura el logger raiz (root) del sistema.

    Para el laboratorio se mantiene la firma original con parametros
    adicionales opcionales. Se debe invocar dentro del proceso worker,
    preferiblemente durante el lifespan de FastAPI, no antes de un fork.

    Cada PID crea su propio fichero: logs/app.pid-12345.log.
    Los handlers externos de Uvicorn o Gunicorn no se eliminan.
    """
    # Asegurar que el directorio del log existe.
    destino = _ruta_por_proceso(log_file)
    destino.parent.mkdir(parents=True, exist_ok=True)

    # Definicion del formato: UTC, PID, nivel, modulo y mensaje.
    log_format = _UTCFormatter(
        "%(asctime)s [PID=%(process)d] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    # Configuracion del Root Logger. El nivel global es INFO, no DEBUG.
    # Para activar DEBUG en un ensayo, pasar level=logging.DEBUG.
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Retirar solo los handlers creados por este modulo. Si el proceso ha
    # heredado handlers tras un fork, no deben seguir apuntando al fichero
    # del padre. Los handlers ajenos se conservan.
    for handler in tuple(root_logger.handlers):
        if getattr(handler, "_oracle_lab_managed", False):
            root_logger.removeHandler(handler)
            handler.close()

    # 1. Handler de archivo por worker (rotacion independiente por PID).
    file_handler = RotatingFileHandler(
        destino,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(log_format)
    file_handler.setLevel(level)
    file_handler._oracle_lab_managed = True
    root_logger.addHandler(file_handler)

    # 2. Handler de consola (si no hay uno ya configurado en root).
    # Evita duplicar la salida cuando Gunicorn configura la consola.
    tiene_consola = any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
        for h in root_logger.handlers
    )
    if console and not tiene_consola:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_format)
        console_handler.setLevel(level)
        console_handler._oracle_lab_managed = True
        root_logger.addHandler(console_handler)

    # En el logger original se silenciaban uvicorn, uvicorn.access,
    # uvicorn.error y fastapi a nivel WARNING. En este laboratorio NO
    # aplicamos ese filtro: los errores y accesos del servidor son parte
    # de la evidencia que queremos conservar y correlacionar por PID.
    logging.getLogger("FastAPIOracleLab").info(
        "Logging inicializado | PID=%s | fichero=%s | nivel=%s",
        os.getpid(), destino, logging.getLevelName(level),
    )


def get_logger(nombre_modulo: str) -> logging.Logger:
    """
    Retorna una instancia de logger configurada para un modulo especifico.

    Se mantiene la interfaz del Backend_Oracle para que config_loader.py
    funcione sin adaptaciones. El nivel se hereda del logger raiz; si un
    ensayo necesita DEBUG, debe configurarlo de forma explicita.
    """
    logger = logging.getLogger(nombre_modulo)
    logger.setLevel(logging.NOTSET)
    return logger
