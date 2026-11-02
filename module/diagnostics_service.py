"""
module.diagnostics_service
==========================

F3/F4 - Metricas internas del pool por proceso FastAPI.

No adquiere conexiones Oracle. Solo informa del pool del PID actual; no se
atribuyen al worker sesiones de otros procesos ni se suman pools inexistentes.
Un pool con opened=0 y ciclo_de_vida=ABIERTO no es un pool cerrado.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any

import oracledb

from module.oracle_client import OracleClient


def utc_now() -> str:
    """Marca temporal UTC sin ambiguedad de huso."""
    return datetime.now(timezone.utc).isoformat()


class DiagnosticsService:
    """Proporciona instantaneas sin tocar una conexion Oracle."""

    def __init__(self, db_client: OracleClient, *, identifier: str,
                 app_name: str, started_at: str):
        self.db_client = db_client
        self.identifier = identifier
        self.app_name = app_name
        self.started_at = started_at
        self._pool_closed = False
        self.pool_identity = id(db_client.pool)

    def marcar_cerrado(self) -> None:
        """Se llama DESPUES del cierre por el propietario del pool (lifespan)."""
        self._pool_closed = True

    def worker(self) -> dict[str, Any]:
        """Identidad del worker; no consulta ni crea conexiones Oracle."""
        return {
            "fecha_utc": utc_now(),
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "python": sys.version.split()[0],
            "python_oracledb": oracledb.__version__,
            "oracle_client_version": OracleClient.__version__,
            "modo_oracle": "THIN" if oracledb.is_thin_mode() else "THICK",
            "client_identifier": self.identifier,
            "client_info": self.app_name,
            "pool_identity": self.pool_identity,
            "inicio_worker_utc": self.started_at,
        }

    def pool(self) -> dict[str, Any]:
        """Instantanea interna: no abre cursor ni llama a acquire()."""
        base = self.worker()
        base["ciclo_de_vida"] = "CERRADO" if self._pool_closed else "ABIERTO"
        base["estado_medicion"] = "OK"
        if self._pool_closed:
            base["opened"] = None
            base["busy"] = None
            return base
        pool = self.db_client.pool
        try:
            base.update({
                "opened": pool.opened,
                "busy": pool.busy,
                "min": pool.min,
                "max": pool.max,
                "increment": pool.increment,
                "timeout": pool.timeout,
                "getmode": str(pool.getmode),
            })
        except Exception:
            base["estado_medicion"] = "NO_DISPONIBLE"
            base["opened"] = None
            base["busy"] = None
        return base
