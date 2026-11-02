"""
module.test_service
===================

F3/F4 - Logica de negocio del laboratorio FastAPI/Oracle 19c.

Responsabilidades:
- CRUD sobre AHJPS_M.LAB_POOL_REGISTROS, aislado por RUN_ID.
- Ejecucion de SP_LAB_POOL_OPERACION con dos parametros OUT.
- Reutilizar el OracleClient que es propiedad del lifespan de FastAPI.
- Clasificar fallos Oracle sin exponer detalles de conexion al cliente HTTP.

El servicio NO crea pools, NO cierra conexiones ni usa SQL dinamico con entradas
externas. El OracleClient original 1.6.2 gestiona el commit del DML y del SP.
El SELECT posterior a un INSERT/UPDATE ya comprometido es otra operacion:
no se debe interpretar la respuesta HTTP como una transaccion multi-sentencia.
"""

from __future__ import annotations

import os
import re
from decimal import Decimal
from typing import Any

import oracledb

from module.oracle_client import OracleClient
from utils.logger import get_logger

LOGGER = get_logger("LabTestService")

# Esquema validado en la fase F1/F2. Constante, NUNCA interpolada desde HTTP.
TABLE = "AHJPS_M.LAB_POOL_REGISTROS"
PROCEDURE = "AHJPS_M.SP_LAB_POOL_OPERACION"

COLUMNS = "ID, RUN_ID, CODIGO, DESCRIPCION, VALOR, ESTADO, FCREACION, FMODIFICACION"


class LabServiceError(Exception):
    """Error funcional o tecnico convertible a un codigo HTTP seguro."""

    def __init__(self, status_code: int, detail: str, *, oracle_code: str | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.oracle_code = oracle_code


class TestService:
    """Servicio SIN estado por peticion; comparte el pool del worker."""

    def __init__(self, db_client: OracleClient):
        self.db_client = db_client

    @staticmethod
    def _run_id(run_id: str) -> str:
        """Evita consultas globales cuando RUN_ID llega vacio o invalido."""
        if not isinstance(run_id, str) or not run_id.strip() or len(run_id.strip()) > 64:
            raise LabServiceError(422, "run_id obligatorio (maximo 64 caracteres)")
        return run_id.strip()

    @staticmethod
    def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
        """Convierte columnas Oracle en un contrato JSON estable."""
        lowered = {str(k).lower(): v for k, v in row.items()}
        return {name: lowered.get(name) for name in (
            "id", "run_id", "codigo", "descripcion", "valor",
            "estado", "fcreacion", "fmodificacion",
        )}

    @staticmethod
    def _handle_db(result: dict[str, Any], operation: str, run_id: str) -> dict[str, Any]:
        """Distingue conflictos funcionales de fallos de infraestructura."""
        if result.get("success"):
            return result
        raw = str(result.get("error") or "Error desconocido de Oracle")
        match = re.search(r"ORA-\d{5}|DPY-\d{4}", raw)
        code = match.group(0) if match else None
        LOGGER.error("Oracle fallo | op=%s run_id=%s pid=%s code=%s detalle=%s",
                     operation, run_id, os.getpid(), code, raw)
        if code == "ORA-00001":
            raise LabServiceError(409, "Ya existe un registro con ese codigo para el run_id", oracle_code=code)
        if code in ("ORA-20013", "ORA-20014"):
            # No revelamos si un ID pertenece a otra campana.
            raise LabServiceError(404, "Registro no encontrado para el run_id", oracle_code=code)
        if code in ("ORA-20010", "ORA-20011", "ORA-20012", "ORA-01400", "ORA-02290"):
            raise LabServiceError(422, "Datos rechazados por las restricciones de Oracle", oracle_code=code)
        if code and code.startswith("DPY-"):
            raise LabServiceError(503, "Oracle no disponible para esta operacion", oracle_code=code)
        raise LabServiceError(500, "Fallo interno ejecutando la operacion Oracle", oracle_code=code)

    def _query(self, sql: str, binds: dict[str, Any], operation: str, run_id: str) -> list[dict]:
        result = self.db_client.execute_query_json(sql, binds)
        self._handle_db(result, operation, run_id)
        return result.get("rows") or []

    def _dml(self, sql: str, binds: dict[str, Any], operation: str, run_id: str) -> int:
        result = self.db_client.execute_dml(sql, binds)
        self._handle_db(result, operation, run_id)
        return int(result.get("rowcount", 0))

    def obtener(self, record_id: int, run_id: str) -> dict[str, Any]:
        """SELECT por ID y RUN_ID; no expone registros de otra campana."""
        run_id = self._run_id(run_id)
        rows = self._query(
            f"SELECT {COLUMNS} FROM {TABLE} WHERE ID = :id AND RUN_ID = :run_id",
            {"id": record_id, "run_id": run_id}, "SELECT_ONE", run_id,
        )
        if not rows:
            raise LabServiceError(404, "Registro no encontrado para el run_id")
        return self._serialize_row(rows[0])

    def listar(self, run_id: str, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        """SELECT paginado; nunca consulta todos los RUN_ID indiscriminadamente."""
        run_id = self._run_id(run_id)
        rows = self._query(
            f"SELECT {COLUMNS} FROM {TABLE} "
            "WHERE RUN_ID = :run_id ORDER BY ID "
            "OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY",
            {"run_id": run_id, "offset": offset, "limit": limit}, "SELECT_LIST", run_id,
        )
        return {"success": True, "run_id": run_id, "limit": limit,
                "offset": offset, "registros": [self._serialize_row(r) for r in rows]}

    def crear(self, *, run_id: str, codigo: str, descripcion: str | None,
              valor: Decimal, estado: str) -> dict[str, Any]:
        """INSERT comprometido por execute_dml; recuperacion posterior por clave unica."""
        run_id = self._run_id(run_id)
        if not codigo or not codigo.strip():
            raise LabServiceError(422, "codigo obligatorio")
        codigo = codigo.strip()
        affected = self._dml(
            f"INSERT INTO {TABLE} "
            "(RUN_ID, CODIGO, DESCRIPCION, VALOR, ESTADO) "
            "VALUES (:run_id, :codigo, :descripcion, :valor, :estado)",
            {"run_id": run_id, "codigo": codigo, "descripcion": descripcion,
             "valor": valor, "estado": estado}, "INSERT", run_id,
        )
        if affected != 1:
            LOGGER.error("INSERT devolvio %s filas para run_id=%s", affected, run_id)
            raise LabServiceError(500, "INSERT no afecto exactamente una fila")
        rows = self._query(
            f"SELECT {COLUMNS} FROM {TABLE} WHERE RUN_ID = :run_id AND CODIGO = :codigo",
            {"run_id": run_id, "codigo": codigo}, "SELECT_AFTER_INSERT", run_id,
        )
        if len(rows) != 1:
            LOGGER.error("INSERT confirmado sin lectura posterior run_id=%s codigo=%s", run_id, codigo)
            raise LabServiceError(500, "INSERT confirmado, pero no se pudo recuperar el registro")
        registro = self._serialize_row(rows[0])
        LOGGER.info("CRUD INSERT | pid=%s run_id=%s id=%s", os.getpid(), run_id, registro["id"])
        return {"success": True, "registro": registro}

    def actualizar(self, record_id: int, *, run_id: str, codigo: str,
                   descripcion: str | None, valor: Decimal, estado: str) -> dict[str, Any]:
        """PUT completo, limitado a ID+RUN_ID y con actualizacion de FMODIFICACION."""
        run_id = self._run_id(run_id)
        if not codigo or not codigo.strip():
            raise LabServiceError(422, "codigo obligatorio")
        affected = self._dml(
            f"UPDATE {TABLE} SET CODIGO = :codigo, DESCRIPCION = :descripcion, "
            "VALOR = :valor, ESTADO = :estado, FMODIFICACION = SYSTIMESTAMP "
            "WHERE ID = :id AND RUN_ID = :run_id",
            {"id": record_id, "run_id": run_id, "codigo": codigo.strip(),
             "descripcion": descripcion, "valor": valor, "estado": estado},
            "UPDATE", run_id,
        )
        if affected == 0:
            raise LabServiceError(404, "Registro no encontrado para el run_id")
        if affected != 1:
            raise LabServiceError(500, "UPDATE afecto un numero inesperado de filas")
        LOGGER.info("CRUD UPDATE | pid=%s run_id=%s id=%s", os.getpid(), run_id, record_id)
        return {"success": True, "registro": self.obtener(record_id, run_id)}

    def eliminar(self, record_id: int, run_id: str) -> dict[str, Any]:
        """DELETE fisico de una sola fila del RUN_ID proporcionado."""
        run_id = self._run_id(run_id)
        affected = self._dml(
            f"DELETE FROM {TABLE} WHERE ID = :id AND RUN_ID = :run_id",
            {"id": record_id, "run_id": run_id}, "DELETE", run_id,
        )
        if affected == 0:
            raise LabServiceError(404, "Registro no encontrado para el run_id")
        if affected != 1:
            raise LabServiceError(500, "DELETE afecto un numero inesperado de filas")
        LOGGER.info("CRUD DELETE | pid=%s run_id=%s id=%s", os.getpid(), run_id, record_id)
        return {"success": True, "id": record_id, "run_id": run_id, "filas_afectadas": affected}

    def ejecutar_procedimiento(self, record_id: int, *, run_id: str,
                              nuevo_valor: Decimal) -> dict[str, Any]:
        """Llama al SP real con la firma (IN, IN, IN, OUT VARCHAR, OUT NUMBER).

        call_procedure_out_scalars() del OracleClient 1.6.2 hace COMMIT. La
        operacion Oracle puede devolver ORA-20013 / ORA-20014 sin actualizar.
        """
        run_id = self._run_id(run_id)
        result = self.db_client.call_procedure_out_scalars(
            PROCEDURE,
            [record_id, nuevo_valor, run_id],
            [str, oracledb.DB_TYPE_NUMBER],
        )
        self._handle_db(result, "SP_OPERACION", run_id)
        output = result.get("output") or []
        if len(output) != 2:
            raise LabServiceError(500, "Procedimiento sin los dos parametros de salida esperados")
        status, affected = output
        if status != "OK" or affected is None or int(affected) != 1:
            LOGGER.error("SP resultado inesperado pid=%s run_id=%s status=%r rows=%r",
                         os.getpid(), run_id, status, affected)
            raise LabServiceError(500, "El procedimiento devolvio un resultado inesperado")
        LOGGER.info("SP OPERACION | pid=%s run_id=%s id=%s rows=%s",
                    os.getpid(), run_id, record_id, int(affected))
        return {"success": True, "id": record_id, "run_id": run_id,
                "resultado": status, "filas_afectadas": int(affected),
                "registro": self.obtener(record_id, run_id)}
