"""
FastAPI_Oracle_Lab - main.py
===========================

F3/F4 - Entrada FastAPI y ciclo de vida del pool Oracle por worker.

Caracteristicas:
- No crea conexiones Oracle al importar este modulo (seguro ante fork).
- Crea UN OracleClient y UN TestService por worker, durante lifespan.
- Usa el OracleClient 1.6.2 original, sin alterar timeout ni getmode.
- Cierra el pool una sola vez, durante el apagado del worker.
- Expone /health sin Oracle y /diagnostics/* sin adquirir conexiones.
- T06 agrega /concurrency/hold sin modificar OracleClient ni el CRUD.
- Registra PID/PPID, versiones y parametros efectivos para comparacion.

IMPORTANTE: no incluye scheduler ni otros procesos capaces de cerrar el pool.
Las credenciales nunca se incluyen en los logs.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import oracledb
from fastapi import FastAPI, Request

from module.config_loader import ConfigLoader
from module.oracle_client import OracleClient
from module.test_service import TestService
from module.diagnostics_service import DiagnosticsService, utc_now
from router import test_api, diagnostics_api, concurrency_api
from utils.logger import get_logger, setup_logger

ROOT = Path(__file__).resolve().parent
LOG = get_logger("FastAPIOracleLab")


def _load_configuration() -> tuple[dict, dict]:
    """Carga los JSON desde el directorio del proyecto y comprueba su contrato."""
    loader = ConfigLoader()
    config = loader.load(ROOT / "config" / "config.json")
    creds = loader.load(ROOT / "config" / "credenciales.json")

    if not isinstance(config, dict) or not isinstance(config.get("oracle"), dict):
        raise RuntimeError("config/config.json no contiene bloque 'oracle' valido")
    if not isinstance(config.get("identificadores"), dict):
        raise RuntimeError("config/config.json no contiene bloque 'identificadores'")
    if not isinstance(creds, dict) or not isinstance(creds.get("LAB_API"), dict):
        raise RuntimeError("config/credenciales.json no contiene bloque 'LAB_API'")
    if any(not creds["LAB_API"].get(k) for k in
           ("servidor", "puerto", "database", "usuario", "password")):
        raise RuntimeError("config/credenciales.json tiene campos LAB_API vacios")
    if config["identificadores"].get("client_identifier_base") != "LAB_POOL_API":
        raise RuntimeError("CLIENT_IDENTIFIER esperado: LAB_POOL_API")
    return config, creds


def _startup_logger(config: dict) -> None:
    """Inicializa un fichero de log distinto en cada PID de Gunicorn."""
    settings = config.get("logging", {})
    relative = settings.get("archivo_base", "logs/app.log")
    path = Path(relative)
    if not path.is_absolute():
        path = ROOT / path
    level = getattr(logging, str(settings.get("nivel", "INFO")).upper(), logging.INFO)
    setup_logger(
        log_file=str(path),
        max_bytes=int(settings.get("max_bytes", 5242880)),
        backup_count=int(settings.get("backup_count", 5)),
        level=level,
        console=bool(settings.get("consola", True)),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Propietario del OracleClient: solo este contexto puede cerrarlo."""
    config, creds = _load_configuration()
    _startup_logger(config)
    pool_config = config["oracle"]
    identifiers = config["identificadores"]
    pid = os.getpid()
    app_name = f"{identifiers.get('app_name', 'FastAPI_Oracle_Lab')}/PID={pid}"
    if len(app_name.encode("utf-8")) > 64:
        raise RuntimeError("app_name/PID supera 64 bytes; reducir identificador")

    pool_min = int(pool_config.get("pool_min", 0))
    pool_max = int(pool_config.get("pool_max", 5))
    retry = int(pool_config.get("retry", 1))
    if pool_min < 0 or pool_max < max(pool_min, 1) or pool_max > 50 or retry < 0 or retry > 3:
        raise RuntimeError("Configuracion Oracle pool_min/pool_max/retry fuera de limites")

    app.state.test_service = None
    app.state.diagnostics_service = None
    app.state.oracle_client = None
    app.state.started_at = utc_now()

    # En la linea base 1.6.2, timeout/getmode/increment son valores internos.
    # Registramos discrepancias, SIN cambiar la biblioteca que medimos.
    declared = {"increment": 1, "timeout": 60, "getmode": "WAIT", "wait_timeout": 30}
    for key, expected in declared.items():
        if pool_config.get(key, expected) != expected:
            LOG.warning("Configuracion declarada %s=%r difiere de OracleClient 1.6.2=%r; "
                        "la clase original prevalece", key, pool_config.get(key), expected)

    client: OracleClient | None = None
    diagnostics: DiagnosticsService | None = None
    try:
        # Se ejecuta una vez por proceso worker, nunca en el master Gunicorn.
        client = OracleClient(
            cfg=creds["LAB_API"],
            pool_min=pool_min,
            pool_max=pool_max,
            retry=retry,
            app_name=app_name,
            user_app="LAB_POOL_API",
        )
        app.state.oracle_client = client
        app.state.test_service = TestService(client)
        diagnostics = DiagnosticsService(
            client,
            identifier="LAB_POOL_API",
            app_name=app_name,
            started_at=app.state.started_at,
        )
        app.state.diagnostics_service = diagnostics
        LOG.info("WORKER START | pid=%s ppid=%s python_oracledb=%s mode=%s oracle_client=%s "
                 "pool_id=%s opened=%s busy=%s min=%s max=%s timeout=%s app_name=%s",
                 pid, os.getppid(), oracledb.__version__,
                 "THIN" if oracledb.is_thin_mode() else "THICK", OracleClient.__version__,
                 id(client.pool), client.pool.opened, client.pool.busy,
                 client.pool.min, client.pool.max, client.pool.timeout, app_name)
        yield
    finally:
        # Starlette/FastAPI espera a las solicitudes en curso antes de finalizar
        # lifespan bajo apagado ordenado. Un SIGKILL no permite limpieza Python.
        if client is not None:
            try:
                LOG.info("WORKER STOP (before close) | pid=%s opened=%s busy=%s",
                         pid, client.pool.opened, client.pool.busy)
                client.close()
                if diagnostics is not None:
                    diagnostics.marcar_cerrado()
                LOG.info("WORKER STOP (pool closed) | pid=%s pool_id=%s", pid, id(client.pool))
            except Exception:
                LOG.exception("WORKER STOP (error closing pool) | pid=%s", pid)
            finally:
                app.state.oracle_client = None
                app.state.test_service = None
                app.state.diagnostics_service = None


app = FastAPI(
    title="FastAPI Oracle Lab",
    description="Laboratorio independiente de pools Oracle, CRUD y diagnosticos por worker",
    version="0.1.0-F3F4",
    lifespan=lifespan,
)

app.include_router(test_api.router)
app.include_router(diagnostics_api.router)

# T06: unica ruta adicional de carga; usa el OracleClient del lifespan.
# No se crean pools ni se importan conexiones a nivel de modulo.
app.include_router(concurrency_api.router)


@app.middleware("http")
async def registrar_peticion(request: Request, call_next):
    """Mide HTTP, sin consultar BD ni acceder al contenido de la peticion."""
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        LOG.exception("HTTP EXCEPTION | pid=%s %s %s", os.getpid(), request.method, request.url.path)
        raise
    ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Lab-Worker-PID"] = str(os.getpid())
    response.headers["X-Lab-Process-Time-Ms"] = str(ms)
    LOG.info("HTTP | pid=%s method=%s path=%s status=%s duration_ms=%s run_id_query=%s",
             os.getpid(), request.method, request.url.path, response.status_code, ms,
             request.query_params.get("run_id", "-"))
    return response


@app.get("/api/v1/lab/health", tags=["Laboratorio - Salud"])
def health():
    """Salud del proceso sin acceso Oracle: no activa conexiones por si mismo."""
    return {"success": True, "estado": "OK", "pid": os.getpid(),
            "fecha_utc": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    # Solo desarrollo; scripts/start_uvicorn.sh se implementara en F5.
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8010, workers=1)
