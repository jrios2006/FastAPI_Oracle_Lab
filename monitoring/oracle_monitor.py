"""Monitor Oracle F6 independiente de los pools medidos.

Solo consulta ``V$SESSION`` mediante la cuenta ``LAB_MONITOR`` y un cliente
OracleClient propio de ESTE proceso, identificado como LAB_POOL_MONITOR.
Nunca reutiliza el pool de una aplicacion FastAPI y no consulta tablas de
produccion. Se excluye del conteo porque filtramos ``LAB_POOL_API``.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from module.oracle_client import OracleClient

_SESSION_SQL = """
SELECT SID, SERIAL#, CLIENT_INFO, STATUS, LAST_CALL_ET, LOGON_TIME
FROM V$SESSION
WHERE CLIENT_IDENTIFIER = :api_identifier
  AND CLIENT_INFO LIKE :client_info_prefix
ORDER BY CLIENT_INFO, SID
"""
_PID = re.compile(r"/PID=(\d+)$")


def _json_safe(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


class OracleMonitor:
    """Obtiene muestras puntuales por sesion y totales de LAB_POOL_API."""

    def __init__(self, client: OracleClient):
        self.client = client

    def snapshot(self) -> dict:
        result = self.client.execute_query(
            _SESSION_SQL,
            {
                "api_identifier": "LAB_POOL_API",
                "client_info_prefix": "FastAPI_Oracle_Lab/PID=%",
            },
        )
        if not result.get("success"):
            # No computar fallo de permisos o conectividad como cero sesiones.
            raise RuntimeError("No se pudo consultar V$SESSION: " + str(result.get("error")))
        columns = [str(name).lower() for name in result.get("columns", [])]
        rows = []
        for values in result.get("rows", []):
            row = {columns[i]: _json_safe(values[i]) for i in range(min(len(columns), len(values)))}
            client_info = str(row.get("client_info") or "")
            match = _PID.search(client_info)
            if not match:
                continue
            row["worker_pid"] = int(match.group(1))
            rows.append(row)
        return {
            "sessions": rows,
            "total": len(rows),
            "active": sum(str(r.get("status", "")).upper() == "ACTIVE" for r in rows),
            "inactive": sum(str(r.get("status", "")).upper() == "INACTIVE" for r in rows),
            "workers_with_sessions": len({r["worker_pid"] for r in rows}),
        }
