#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts.validar_conexiones
==========================

FastAPI_Oracle_Lab - F2. Validacion de conectividad y permisos Oracle.

Objetivos:
  - Comprobar dos conexiones REALES y separadas usando el OracleClient
    original (version 1.6.2, sin modificaciones funcionales).
  - Verificar los marcadores CLIENT_IDENTIFIER del laboratorio.
  - Validar el acceso a la tabla/procedimiento y a las vistas de monitorizacion.
  - Guardar evidencia JSON sin credenciales en reports/resultados/.

Seguridad:
  - NO modifica datos ni llama a procedimientos con efectos secundarios.
  - NO muestra usuarios, contrasenas ni cadenas de conexion.
  - NO reutiliza un mismo pool para API y monitor.

Uso desde la raiz del proyecto:
    python scripts/validar_conexiones.py
    python scripts/validar_conexiones.py --solo-config
    python scripts/validar_conexiones.py --owner AHJPS_M

Salida: codigo 0 si todas las comprobaciones obligatorias pasan; 1 si fallan.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from module.config_loader import ConfigLoader
from module.oracle_client import OracleClient
import oracledb


CONFIG_FILE = PROJECT_ROOT / "config" / "config.json"
CREDENTIALS_FILE = PROJECT_ROOT / "config" / "credenciales.json"
REPORT_DIR = PROJECT_ROOT / "reports" / "resultados"
IDENT_API = "LAB_POOL_API"
IDENT_MONITOR = "LAB_POOL_MONITOR"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_error(value: Any, passwords: tuple[str, ...]) -> str:
    """Oculta los secretos si una libreria los reprodujera en una excepcion."""
    output = str(value)
    for secret in passwords:
        if secret:
            output = output.replace(secret, "[SECRETO_OCULTO]")
    return output[:600]


class Validacion:
    """Conserva los resultados sin datos de autenticacion."""

    def __init__(self, passwords: tuple[str, ...]):
        self.passwords = passwords
        self.checks: list[dict[str, Any]] = []
        self.inicio = utc_now()

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        item = {
            "prueba": name,
            "resultado": "APTO" if ok else "NO_APTO",
            "detalle": safe_error(detail, self.passwords),
            "utc": utc_now(),
        }
        self.checks.append(item)
        print(f"[{'OK' if ok else 'ERROR'}] {name}: {item['detalle']}")

    def warning(self, detail: str) -> None:
        item = {"prueba": "AVISO", "resultado": "AVISO", "detalle": safe_error(detail, self.passwords), "utc": utc_now()}
        self.checks.append(item)
        print(f"[AVISO] {item['detalle']}")

    def save(self, *, config_only: bool = False) -> Path:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"validacion_oracle_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{os.getpid()}.json"
        result = {
            "laboratorio": "FastAPI_Oracle_Lab",
            "tipo": "CONFIGURACION" if config_only else "CONEXIONES_REALES",
            "fecha_inicio_utc": self.inicio,
            "fecha_fin_utc": utc_now(),
            "pid": os.getpid(),
            "python": sys.version.split()[0],
            "python_oracledb": oracledb.__version__,
            "modo_oracle": "THIN" if oracledb.is_thin_mode() else "THICK",
            "version_oracle_client_laboratorio": OracleClient.__version__,
            "validacion_global": "APTO" if all(x['resultado'] != 'NO_APTO' for x in self.checks) else "NO_APTO",
            "comprobaciones": self.checks,
        }
        path = REPORT_DIR / filename
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return path


def query_ok(client: OracleClient, sql: str, params: dict | None = None) -> tuple[bool, list[dict], str]:
    """Ejecuta SELECT por OracleClient, sin acceso directo al pool medido."""
    result = client.execute_query_json(sql, params or {})
    if result.get("success"):
        return True, result.get("rows", []), ""
    return False, [], str(result.get("error") or "Consulta Oracle fallida")


def pool_snapshot(client: OracleClient) -> str:
    pool = client.pool
    return f"opened={pool.opened}, busy={pool.busy}, min={pool.min}, max={pool.max}, timeout={pool.timeout}"


def validar_estructura(cred: dict, cfg: dict, output: Validacion) -> bool:
    ok = True
    for name in ("LAB_API", "LAB_MONITOR"):
        section = cred.get(name)
        valid = isinstance(section, dict) and all(
            isinstance(section.get(key), (str, int)) and str(section[key]).strip()
            for key in ("servidor", "puerto", "database", "usuario", "password")
        )
        if valid:
            valid = str(section["password"]).strip() != "REEMPLAZAR_LOCALMENTE" and str(section["servidor"]).strip() != "HOST_ORACLE"
        output.check(f"Credenciales {name} - estructura", bool(valid),
                     "Cinco campos presentes; valores reales detectados" if valid else "Faltan campos o hay valores de ejemplo")
        ok &= bool(valid)
    has_cfg = isinstance(cfg.get("oracle"), dict) and isinstance(cfg.get("identificadores"), dict)
    output.check("config.json - estructura", has_cfg,
                 "Secciones oracle e identificadores presentes" if has_cfg else "Secciones requeridas ausentes")
    ok &= has_cfg
    if has_cfg:
        ids = cfg['identificadores']
        marks = ids.get('client_identifier_base') == IDENT_API and ids.get('monitor_identifier') == IDENT_MONITOR
        output.check("Etiquetas de sesion", marks, "API=LAB_POOL_API; monitor=LAB_POOL_MONITOR" if marks else "Etiquetas no coinciden con el SQL del laboratorio")
        ok &= marks
        pool_cfg = cfg['oracle']
        if (pool_cfg.get('pool_min'), pool_cfg.get('pool_max'), pool_cfg.get('timeout')) != (0, 5, 60):
            output.warning("La configuracion declarada difiere del valor por defecto de OracleClient 1.6.2; el cliente original fija timeout=60 internamente")
        else:
            output.warning("OracleClient original fija timeout=60 y getmode=WAIT; este script solo inyecta pool_min, pool_max y retry")
    return bool(ok)


def ejecutar(cred: dict, cfg: dict, owner: str, output: Validacion) -> None:
    oracle_cfg = cfg.get('oracle', {})
    api = None
    monitor = None
    retry = int(oracle_cfg.get('retry', 1))
    pool_min = int(oracle_cfg.get('pool_min', 0))
    pool_max = int(oracle_cfg.get('pool_max', 5))
    if pool_min < 0 or pool_max < max(pool_min, 1) or pool_max > 50:
        output.check('Parametros de pool', False, 'Valores min/max invalidos o no seguros para la prevalidacion')
        return

    try:
        t0 = time.perf_counter()
        api = OracleClient(cfg=cred['LAB_API'], pool_min=pool_min, pool_max=pool_max,
                           retry=retry, app_name='FastAPI_Oracle_Lab/VALIDACION', user_app=IDENT_API)
        output.check('LAB_API - crear pool', True, f"{pool_snapshot(api)} | {round((time.perf_counter()-t0)*1000,1)} ms")

        ok, rows, err = query_ok(api, """
            SELECT USER AS USUARIO,
                   SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') AS ESQUEMA,
                   SYS_CONTEXT('USERENV', 'SERVICE_NAME') AS SERVICIO,
                   SYS_CONTEXT('USERENV', 'CLIENT_IDENTIFIER') AS IDENTIFICADOR
            FROM DUAL
        """)
        output.check('LAB_API - conexion real', ok and len(rows) == 1 and rows[0].get('IDENTIFICADOR') == IDENT_API,
                     'Conexion y CLIENT_IDENTIFIER verificados' if ok and rows and rows[0].get('IDENTIFICADOR') == IDENT_API else err or 'Identificador de sesion incorrecto')

        ok, rows, err = query_ok(api, """
            SELECT OBJECT_NAME, OBJECT_TYPE, STATUS
            FROM ALL_OBJECTS
            WHERE OWNER = :owner
              AND OBJECT_NAME IN ('LAB_POOL_REGISTROS', 'SP_LAB_POOL_OPERACION')
        """, {"owner": owner})
        found = {(r['OBJECT_NAME'], r['OBJECT_TYPE']): r['STATUS'] for r in rows} if ok else {}
        objects_ok = found.get(('LAB_POOL_REGISTROS','TABLE')) == 'VALID' and found.get(('SP_LAB_POOL_OPERACION','PROCEDURE')) == 'VALID'
        output.check('LAB_API - objetos Oracle', ok and objects_ok,
                     'Tabla y procedimiento VALID visibles para la cuenta API' if objects_ok else err or 'Objetos no visibles o no validos')

        ok, rows, err = query_ok(api, f"SELECT ID FROM {owner}.LAB_POOL_REGISTROS WHERE 1 = 0")
        output.check('LAB_API - permiso SELECT', ok,
                     'SELECT sin recuperar datos ni modificar registros' if ok else err)

        t0 = time.perf_counter()
        monitor = OracleClient(cfg=cred['LAB_MONITOR'], pool_min=0, pool_max=1,
                               retry=retry, app_name='FastAPI_Oracle_Lab/MONITOR', user_app=IDENT_MONITOR)
        output.check('LAB_MONITOR - crear pool independiente', True,
                     f"{pool_snapshot(monitor)} | {round((time.perf_counter()-t0)*1000,1)} ms")

        ok, rows, err = query_ok(monitor, """
            SELECT SYS_CONTEXT('USERENV', 'CLIENT_IDENTIFIER') AS IDENTIFICADOR FROM DUAL
        """)
        output.check('LAB_MONITOR - conexion real', ok and len(rows)==1 and rows[0].get('IDENTIFICADOR') == IDENT_MONITOR,
                     'Conexion e identificador de monitor verificados' if ok and rows and rows[0].get('IDENTIFICADOR') == IDENT_MONITOR else err or 'Identificador de sesion incorrecto')

        ok, rows, err = query_ok(monitor, """
            SELECT CLIENT_IDENTIFIER, COUNT(*) AS TOTAL
            FROM V$SESSION
            WHERE TYPE = 'USER'
              AND CLIENT_IDENTIFIER IN (:api_identifier, :monitor_identifier)
            GROUP BY CLIENT_IDENTIFIER
        """, {"api_identifier": IDENT_API, "monitor_identifier": IDENT_MONITOR})
        if ok:
            counts = {r['CLIENT_IDENTIFIER']: r['TOTAL'] for r in rows}
            visible = int(counts.get(IDENT_API, 0)) >= 1 and int(counts.get(IDENT_MONITOR, 0)) >= 1
            output.check('LAB_MONITOR - V$SESSION', visible,
                         f"Sesiones visibles: API={counts.get(IDENT_API,0)}; MONITOR={counts.get(IDENT_MONITOR,0)}")
        else:
            output.check('LAB_MONITOR - V$SESSION', False, err + ' (solicitar SELECT sobre SYS.V_$SESSION al DBA)')

        ok, rows, err = query_ok(monitor, """
            SELECT RESOURCE_NAME, CURRENT_UTILIZATION, LIMIT_VALUE
            FROM V$RESOURCE_LIMIT
            WHERE RESOURCE_NAME IN ('sessions', 'processes')
        """)
        output.check('LAB_MONITOR - V$RESOURCE_LIMIT', ok and len(rows)>0,
                     f"{len(rows)} recursos consultados" if ok else err + ' (solicitar SELECT sobre SYS.V_$RESOURCE_LIMIT al DBA)')
        output.check('LAB_API - pool devuelto', api.pool.busy == 0, pool_snapshot(api))
        output.check('LAB_MONITOR - pool devuelto', monitor.pool.busy == 0, pool_snapshot(monitor))
    except Exception as exc:
        output.check('Ejecucion de conexiones', False, f"{type(exc).__name__}: {exc}")
    finally:
        # La utilidad ES propietaria de estos dos pools, por tanto puede cerrarlos.
        # No se cierra ningun pool perteneciente a FastAPI u otro proceso.
        for label, client in (("LAB_MONITOR", monitor), ("LAB_API", api)):
            if client is not None:
                try:
                    client.close()
                    output.check(f'{label} - cierre de pool', True, 'Cierre explicito al terminar la validacion')
                except Exception as exc:
                    output.check(f'{label} - cierre de pool', False, f'{type(exc).__name__}: {exc}')


def main() -> int:
    parser = argparse.ArgumentParser(description='Valida dos conexiones Oracle independientes del laboratorio.')
    parser.add_argument('--owner', default='AHJPS_M', help='Esquema propietario de LAB_POOL_REGISTROS y SP_LAB_POOL_OPERACION')
    parser.add_argument('--solo-config', action='store_true', help='Solo valida JSON, sin abrir conexiones')
    args = parser.parse_args()

    owner = args.owner.upper().strip()
    if not re.fullmatch(r'[A-Z][A-Z0-9_$#]{0,127}', owner):
        print('[ERROR] Nombre de esquema Oracle no valido', file=sys.stderr)
        return 1

    loader = ConfigLoader()
    cred = loader.load(CREDENTIALS_FILE)
    cfg = loader.load(CONFIG_FILE)
    passwords = tuple(str(part.get('password', '')) for part in cred.values() if isinstance(part, dict)) if isinstance(cred, dict) else ()
    out = Validacion(passwords)
    ready = validar_estructura(cred if isinstance(cred,dict) else {}, cfg if isinstance(cfg,dict) else {}, out)
    if ready and not args.solo_config:
        ejecutar(cred, cfg, owner, out)
    elif not ready:
        out.warning('No se abren conexiones hasta completar la configuracion')
    elif args.solo_config:
        out.warning('Modo solo-config: conectividad Oracle NO comprobada')

    saved = out.save(config_only=args.solo_config)
    print(f'\nInforme sin secretos: {saved}')
    return 1 if any(x['resultado'] == 'NO_APTO' for x in out.checks) else 0


if __name__ == '__main__':
    raise SystemExit(main())
