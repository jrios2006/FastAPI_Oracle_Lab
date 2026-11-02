"""
module.oracle_client
====================

Cliente Oracle avanzado para Python con soporte para consultas clásicas,
DML, procedimientos almacenados y JSON. Incluye gestión de contexto 
transparente para auditoría y trazabilidad en base de datos.

Version: 1.6.2
Build date: 2026-10-23

Mejoras de esta versión (1.6.2):
------------------------
1. Solución de Inactividad Crónica (pool_min=0): Se cambia el valor por defecto 
   del tamaño mínimo del pool de 1 a 0. Esto evita que despliegues multiproceso 
   (como Gunicorn con 21 workers) generen y retengan conexiones genéricas ("N/A") 
   indefinidamente, permitiendo que el timeout limpie el 100% de las sesiones.

Mejoras de versiones anteriores:
------------------------
- Autodestrucción de Conexiones Zombi: Implementación de un TTL (timeout) de 60 segundos 
  en el Pool para purgar automáticamente conexiones inactivas.
- Soporte de Contexto Dinámico: Inyección de CLIENT_IDENTIFIER por transacción.
- Compatibilidad Thin Mode: Uso de bloques PL/SQL para contexto inmediato.
- Modo Rescate de Logs: Captura del buffer DBMS_OUTPUT ante excepciones críticas.
"""

import oracledb
import time
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Generator

class SafeJSONEncoder(oracledb.JSONEncoder if hasattr(oracledb, "JSONEncoder") else object):
    def default(self, obj: Any):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, oracledb.LOB):
            return obj.read()
        return super().default(obj) if hasattr(super(), "default") else str(obj)


class OracleClient:
    __version__ = "1.6.2"
    __build_date__ = "2026-10-23"

    # [VERSIÓN 1.6.2]: pool_min cambia de 1 a 0 por defecto.
    def __init__(self, cfg: dict, pool_min=0, pool_max=5, retry=1, app_name: str = None, user_app: str = None):
        if "BBDD" in cfg:
            cfg = cfg["BBDD"]
        
        self.cfg = cfg
        self.retry = retry
        self.app_name = app_name
        self.user_app = user_app  # Usuario por defecto (fallback)
        self.logger = logging.getLogger("OracleClient")
        
        dsn = f'{cfg["servidor"]}:{cfg["puerto"]}/{cfg["database"]}'
        
        # Inicialización del Pool con reglas estrictas de ciclo de vida
        self.pool = oracledb.create_pool(
            user=cfg["usuario"],
            password=cfg["password"],
            dsn=dsn,
            min=pool_min,
            max=pool_max,
            increment=1,
            getmode=oracledb.POOL_GETMODE_WAIT, 
            wait_timeout=30,
            # [VERSIÓN 1.6.1 / 1.6.2] - TIMEOUT DE PURGA
            # Fuerza a Oracle a desconectar y destruir cualquier conexión que lleve 
            # 60 segundos inactiva en el pool. Al establecer min=0, garantizamos que
            # TODAS las conexiones zombis puedan ser destruidas sin retener un mínimo.
            timeout=60  
        )

    def _set_session_context(self, conn: oracledb.Connection, dynamic_user: str = None):
        # Prioridad: Usuario inyectado en la transacción > Usuario por defecto del Pool
        final_user = dynamic_user or self.user_app
        
        if self.app_name: conn.client_info = self.app_name
        if final_user: conn.client_identifier = final_user

        if self.app_name or final_user:
            with conn.cursor() as cursor:
                cursor.execute("""
                    BEGIN
                        IF :app IS NOT NULL THEN DBMS_APPLICATION_INFO.SET_CLIENT_INFO(:app); END IF;
                        IF :usr IS NOT NULL THEN DBMS_SESSION.SET_IDENTIFIER(:usr); END IF;
                    END;
                """, app=self.app_name, usr=final_user)

    def _result_base(self) -> dict:
        return {
            "library_version": self.__version__,
            "build_date": self.__build_date__,
            "success": False,
            "rows": [],
            "rowcount": 0,
            "output": [],
            "dbms_console": [], 
            "pool_latency": 0.0,  
            "duration": 0.0,      
            "error": None,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    def _fetch_dbms_output(self, cursor) -> list:
        chunk_size = 100
        lines_var = cursor.arrayvar(str, chunk_size)
        num_lines_var = cursor.var(int)
        num_lines_var.setvalue(0, chunk_size)
        
        output_lines = []
        while True:
            cursor.callproc("DBMS_OUTPUT.GET_LINES", (lines_var, num_lines_var))
            num_lines = num_lines_var.getvalue()
            lines = lines_var.getvalue()
            output_lines.extend(lines[:num_lines])
            if num_lines < chunk_size: break
                
        return [line for line in output_lines if line is not None]

    def _execute(self, func, capture_log: bool = False, dynamic_user: str = None) -> dict:
        result = self._result_base()
        attempts = 0
        
        while attempts <= self.retry:
            try:
                pool_start = time.time()
                with self.pool.acquire() as conn:
                    result["pool_latency"] = round((time.time() - pool_start) * 1000, 2)
                    # Inyectamos el contexto dinámico
                    self._set_session_context(conn, dynamic_user)
                    
                    if capture_log:
                        with conn.cursor() as log_cur:
                            log_cur.callproc("DBMS_OUTPUT.ENABLE", [None])
                    
                    db_start = time.time()
                    value = func(conn)
                    result["duration"] = round((time.time() - db_start) * 1000, 2)
                    
                    if isinstance(value, dict): result.update(value)
                    
                    if capture_log:
                        with conn.cursor() as log_cur:
                            result["dbms_console"] = self._fetch_dbms_output(log_cur)
                            
                    result["success"] = True
                    break 
                    
            except Exception as e:
                result["error"] = str(e)
                if capture_log:
                    try:
                        with conn.cursor() as log_cur:
                            result["dbms_console"] = self._fetch_dbms_output(log_cur)
                    except Exception as rescue_e:
                        result["dbms_console"] = [f"No se pudo rescatar el log tras el crash: {rescue_e}"]
                
                attempts += 1
                if attempts > self.retry:
                    self.logger.error(f"Oracle Critical Error en _execute (Intentos agotados): {e}")
        return result

    # ---------------------------------------------------------
    # --- MÉTODOS DE ACCIÓN PÚBLICOS ---
    # ---------------------------------------------------------

    def execute_query(self, query: str, params: dict | None = None, user_app: str = None) -> dict:
        def run(conn):
            with conn.cursor() as cursor:
                cursor.execute(query, params or {})
                rows = cursor.fetchall()
                columns = [d[0] for d in cursor.description]
                return {"rows": rows, "columns": columns, "rowcount": len(rows)}
        return self._execute(run, dynamic_user=user_app)

    def execute_dml(self, query: str, params: dict | None = None, user_app: str = None) -> dict:
        def run(conn):
            with conn.cursor() as cursor:
                cursor.execute(query, params or {})
                conn.commit()
                return {"rowcount": max(cursor.rowcount, 0)}
        return self._execute(run, dynamic_user=user_app)

    def bulk_insert(self, query: str, data: list, batch_size: int = None, user_app: str = None) -> dict:
        def run(conn):
            with conn.cursor() as cursor:
                if batch_size:
                    for i in range(0, len(data), batch_size):
                        cursor.executemany(query, data[i:i + batch_size])
                else:
                    cursor.executemany(query, data)
                conn.commit()
                return {"rowcount": cursor.rowcount}
        return self._execute(run, dynamic_user=user_app)

    def call_procedure(self, proc_name: str, params: list | None = None, capture_log: bool = False, user_app: str = None) -> dict:        
        def run(conn):
            with conn.cursor() as cursor:
                cursor.callproc(proc_name, params or [])
                conn.commit()
                return {}
        return self._execute(run, capture_log=capture_log, dynamic_user=user_app)

    def call_procedure_with_cursor(self, proc_name: str, params: list | None = None, capture_log: bool = False, user_app: str = None) -> dict:
        def run(conn):
            with conn.cursor() as cursor:
                ref_cursor = cursor.var(oracledb.CURSOR)
                args = (params or []) + [ref_cursor]
                cursor.callproc(proc_name, args)
                conn.commit()
                
                out_cur = ref_cursor.getvalue()
                if not out_cur: return {"rows": [], "rowcount": 0, "columns": []}
                
                columns = [col[0] for col in out_cur.description]
                res = []
                for row in out_cur.fetchall():
                    row_dict = {}
                    for col, val in zip(columns, row):
                        if isinstance(val, oracledb.LOB): val = val.read()
                        elif isinstance(val, (datetime, date)): val = val.isoformat()
                        elif isinstance(val, Decimal): val = float(val)
                        row_dict[col.lower()] = val 
                    res.append(row_dict)
                return {"rows": res, "columns": columns, "rowcount": len(res)}
        return self._execute(run, capture_log=capture_log, dynamic_user=user_app)

    def call_procedure_out_scalars(self, proc_name: str, in_params: list, out_types: list, capture_log: bool = False, user_app: str = None) -> dict:
        def run(conn):
            with conn.cursor() as cursor:
                out_vars = [cursor.var(t) for t in out_types]
                args = in_params + out_vars
                cursor.callproc(proc_name, args)
                conn.commit()
                return {"output": [var.getvalue() for var in out_vars]}
        return self._execute(run, capture_log=capture_log, dynamic_user=user_app)

    def execute_query_json(self, query: str, params: dict | None = None, user_app: str = None) -> dict:
        def run(conn):
            with conn.cursor() as cursor:
                cursor.execute(query, params or {})
                columns = [d[0] for d in cursor.description]
                res = []
                for row in cursor.fetchall():
                    row_dict = {}
                    for col, val in zip(columns, row):
                        if isinstance(val, oracledb.LOB): val = val.read()
                        elif isinstance(val, (datetime, date)): val = val.isoformat()
                        elif isinstance(val, Decimal): val = float(val)
                        row_dict[col] = val
                    res.append(row_dict)
                return {"rows": res, "columns": columns, "rowcount": len(res)}
        return self._execute(run, dynamic_user=user_app)

    def stream_query_json(self, query: str, params: dict | None = None, batch_size: int = 1000, user_app: str = None) -> Generator:
        conn = self.pool.acquire()
        try:
            self._set_session_context(conn, dynamic_user=user_app)
            cursor = conn.cursor()
            cursor.execute(query, params or {})
            cols = [d[0] for d in cursor.description]
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows: break
                for row in rows:
                    row_dict = {}
                    for col, val in zip(cols, row):
                        if isinstance(val, oracledb.LOB): val = val.read()
                        elif isinstance(val, (datetime, date)): val = val.isoformat()
                        elif isinstance(val, Decimal): val = float(val)
                        row_dict[col] = val
                    yield row_dict
        finally:
            cursor.close()
            conn.close()

    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): self.close()

    def close(self):
        if self.pool: self.pool.close()
