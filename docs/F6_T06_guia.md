# FastAPI_Oracle_Lab — F6 monitores y F7/T06 concurrencia controlada

**Fecha:** 30/10/2026. **Estado:** implementación entregada; pendiente de validación real desde AIO contra Oracle 19c.

## Objetivo

Medir simultaneidad de sesiones Oracle reales y ocupación de pools de Gunicorn con `OracleClient` **1.6.2 sin modificaciones**. La fase secuencial F5 (1/2/4/8 workers) quedó validada en el entorno AIO con `python-oracledb 26.1.0` Thin. Esta nueva prueba **no** certifica todavía la versión `1.2.1` del backend original.

## Archivos que añade este paquete

- `module/concurrency_service.py`: usa el OracleClient ya existente; un bloque `DBMS_SESSION.SLEEP(:segundos)` ocupa **una conexión Oracle** durante la ejecución.
- `router/concurrency_api.py`: ruta de prueba `POST /api/v1/lab/concurrency/hold`, solo desde loopback; duración entre 0,1 y 5 segundos; método sin escritura de datos.
- `main.py`: versión completa del F3 con **solo el import y el registro del nuevo router**; conserva los comentarios originales. Si tienes cambios locales posteriores al F3, compara el diff antes de sobrescribirlo.
- `monitoring/oracle_monitor.py`: consulta `V$SESSION` con la cuenta independiente `LAB_MONITOR`, excluida por el identificador `LAB_POOL_MONITOR`.
- `monitoring/process_monitor.py`: detecta master/workers Gunicorn usando `ps`.
- `monitoring/metrics_collector.py`: genera CSV por instante, sesiones, procesos y diagnósticos HTTP.
- `scripts/run_monitor.py`: ejecuta el muestreo externo y produce CSV.
- `tests/test_concurrency.py`: cliente HTTP concurrente con límite de 16 peticiones simultáneas y resultados CSV/JSON.
- `scripts/analyze_t06.py`: informe agregado Markdown/JSON de los CSV HTTP, sesiones y pools.
- `README.md`: conserva la especificación anterior y añade el contrato de F6/F7-T06.

## Requisitos

- Linux, Python de `.venv` y los requisitos del laboratorio ya instalados.
- Los mismos `config/config.json` y `config/credenciales.json` de F2 (el ZIP **no contiene credenciales**).
- `LAB_MONITOR` con permiso de lectura sobre `V$SESSION`, validado previamente en F2.
- Usuario Oracle de `LAB_API` con posibilidad de ejecutar `DBMS_SESSION.SLEEP`, disponible en Oracle 19c. No se crearán grants ni procedimientos para esta prueba; si hay `ORA-01031`/`PLS-00201`, detener y revisar permisos.
- No lanzar pruebas de carga en un sistema clínico ni en producción sin autorización. El laboratorio permanece vinculado a `127.0.0.1:8010`.

## Prueba inicial con dos workers (recomendada)

Extrae el ZIP en el directorio **padre** de `FastAPI_Oracle_Lab`, con backup del `README.md` y `main.py` si tienes cambios locales. Para aplicar solo el router en un `main.py` local modificado, incorpora estas dos líneas sin reemplazar el archivo:

```python
from router import test_api, diagnostics_api, concurrency_api
app.include_router(concurrency_api.router)
```

Asegúrate de registrar el router una sola vez, junto a los otros `include_router`.

**Terminal A — Gunicorn:**

```bash
cd ~/Proyectos/FastAPI_Oracle_Lab
source .venv/bin/activate
./scripts/start_gunicorn.sh 2
```

**Terminal B — Prueba de permisos (preflight):**

```bash
curl -sS -i -X POST http://127.0.0.1:8010/api/v1/lab/concurrency/hold \
  -H 'Content-Type: application/json' \
  -d '{"run_id":"LAB_T06_20261030_A","segundos":0.25}'
```

Debe devolver HTTP 200 con `success=true`, `pid`, `espera_pool_ms`, `duracion_operacion_oracle_ms`. Si aparece 500, consultar logs: por ejemplo, permisos de `DBMS_SESSION.SLEEP`. Si aparece 404, el nuevo router no está instalado o el servidor no se reinició.

**Terminal B — Monitor externo:**

```bash
python scripts/run_monitor.py \
  --run-id LAB_T06_20261030_A \
  --duration 130 --interval 1 --http-samples 8
```

Este comando debe comenzar antes de la carga; los 130 segundos permiten registrar tambien el reposo posterior al timeout de 60 s, siempre que la carga se lance sin retrasos excesivos. No reiniciar el monitor durante la prueba. Genera CSV en `reports/sesiones/LAB_T06_20261030_A/`. Verifica que `oracle_totals.csv` tenga filas `status=OK` y que el monitor no informe errores. Separa `LAB_POOL_MONITOR` del `LAB_POOL_API` que estudia.

**Terminal C — Carga controlada:**

```bash
cd ~/Proyectos/FastAPI_Oracle_Lab
source .venv/bin/activate
python tests/test_concurrency.py \
  --run-id LAB_T06_20261030_A \
  --concurrency 4 --requests 12 --seconds 3
```

Genera `reports/rendimiento/LAB_T06_20261030_A/requests.csv` y `summary.json`. El monitor puede terminar de muestrear durante el reposo; no es necesario realizar más solicitudes a Oracle.

**Terminal C — Informe después de finalizar el monitor:**

```bash
python scripts/analyze_t06.py --run-id LAB_T06_20261030_A
```

El informe agregado aparecerá en `reports/resultados/LAB_T06_20261030_A/report.md` y `report.json`. El indicador `APTO_PRELIMINAR` exige, entre otras condiciones, al menos dos sesiones `ACTIVE` observadas simultáneamente y ninguna sesión en la última muestra; `INCONCLUSO_O_REVISAR` no equivale automáticamente a fallo.

## Escalado recomendado

Cuando la primera campaña sea estable, crea **otro `run_id`** para cada ejecución y sube gradualmente: 2 workers / concurrencia 2 → 2 workers / concurrencia 4 → 4 workers / concurrencia 8 → 8 workers / concurrencia 16. Los scripts bloquean más de 16 concurrentes y más de 5 s de espera en Oracle. **No permiten 40 solicitudes concurrentes** en esta etapa. No asumir que `--concurrency 16` abre 16 conexiones: confirmar el pico observado en el monitor.

## Qué mirar en los informes

1. `oracle_totals.csv`: secuencia de `total`, `active`, `inactive`. Cada muestra incluye total 0 cuando es cero; **status=ERROR nunca se convierte en cero**.
2. `oracle_sessions.csv`: PID, SID, SERIAL#, STATUS, LAST_CALL_ET y LOGON_TIME por sesión observada.
3. `pool_samples.csv`: observaciones puntuales desde `/diagnostics/pool`, incluyendo `opened`, `busy`, `max` y `pool_identity`; **con Gunicorn no hay garantía de observar todos los workers en cada intervalo**.
4. `processes.csv`: PID del master y workers detectados en cada muestra.
5. `requests.csv`: una fila por solicitud, worker que la respondió, tiempo HTTP, espera de pool, duración de llamada Oracle y errores.
6. `summary.json`: número de respuestas correctas y distribución de solicitudes por PID.

**Interpretación:** el pico de `oracle_totals.active` y las capturas `pool_samples.busy` proporcionan evidencia de simultaneidad. Su ausencia no demuestra por sí sola que la concurrencia no exista (muestreo puntual). Las duraciones del cliente HTTP tampoco prueban ocupación Oracle sin esas muestras. Comparar sesiones tras la carga y tras un reposo suficiente; la purga por `timeout=60` puede retrasarse.

**Limitación intencionada:** `DBMS_SESSION.SLEEP` simula una llamada Oracle bloqueante, pero no representa el coste funcional de una consulta, transacción o servicio clínico. Tampoco prueba que 40 sesiones en `pisuerga` fueran causadas por el driver: eso requiere repetir condiciones equivalentes, incluida la versión `python-oracledb 1.2.1`, y verificar el número real de workers.

## Limpieza

El nuevo endpoint no inserta, actualiza ni borra datos. Se detiene con Ctrl+C igual que los demás endpoints. El monitor cierra **su propio** OracleClient al finalizar. No borrar los objetos Oracle F1: siguen siendo necesarios para otros ensayos.
