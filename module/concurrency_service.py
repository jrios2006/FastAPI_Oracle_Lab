"""Servicio T06: ocupar temporalmente UNA conexion Oracle del pool existente.

Este servicio es intencionadamente SIN estado y no crea/cierra pools.
Cada peticion ejecuta DBMS_SESSION.SLEEP dentro del ``execute_dml`` del
OracleClient 1.6.2. El metodo adquiere la conexion, ejecuta el bloque PL/SQL,
hace commit (sin cambios de datos) y devuelve la conexion al pool.

Se utiliza DBMS_SESSION.SLEEP, documentado para Oracle 19c. Si el usuario
Oracle no dispone de EXECUTE sobre el paquete, la prueba fallara durante el
preflight, sin aplicar permisos nuevos ni modificar tablas.

NOTA: mide ocupacion de conexiones, NO rendimiento de consultas reales.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from module.oracle_client import OracleClient
from utils.logger import get_logger

LOG = get_logger("LabConcurrencyService")
_PLSQL_SLEEP = "BEGIN DBMS_SESSION.SLEEP(:segundos); END;"
_ERROR_CODE = re.compile(r"(?:ORA-\d{5}|DPY-\d{4})")


@dataclass(frozen=True)
class ConcurrencyLabError(Exception):
    status_code: int
    detail: str


class ConcurrencyService:
    """No almacena conexiones por solicitud: reutiliza el pool del worker."""

    def __init__(self, client: OracleClient):
        self.client = client

    def hold(self, *, run_id: str, segundos: float) -> dict:
        """Mantiene adquirida una conexion en Oracle durante ``segundos``.

        Se utiliza un bloque PL/SQL sin escrituras para que la ocupacion se
        pueda observar con ``pool.busy`` y ``V$SESSION`` en otro proceso.
        Nunca expone al cliente HTTP un error de conexion ni credenciales.
        """
        start = time.perf_counter()
        result = self.client.execute_dml(_PLSQL_SLEEP, {"segundos": segundos})
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        if not result.get("success"):
            raw = str(result.get("error") or "Error Oracle desconocido")
            match = _ERROR_CODE.search(raw)
            code = match.group(0) if match else "SIN_CODIGO"
            LOG.error("T06 HOLD ERROR | run_id=%s pid=%s code=%s", run_id, os.getpid(), code)
            status = 503 if code.startswith("DPY-") else 500
            raise ConcurrencyLabError(status, f"Fallo en prueba Oracle ({code}); consultar logs")
        LOG.info(
            "T06 HOLD OK | run_id=%s pid=%s segundos=%s elapsed_ms=%s pool_wait_ms=%s",
            run_id, os.getpid(), segundos, elapsed_ms, result.get("pool_latency"),
        )
        return {
            "success": True,
            "run_id": run_id,
            "pid": os.getpid(),
            "segundos_solicitados": segundos,
            "duracion_total_ms": elapsed_ms,
            "espera_pool_ms": result.get("pool_latency"),
            "duracion_operacion_oracle_ms": result.get("duration"),
        }
