# FastAPI_Oracle_Lab — Guía de informe consolidado y repeticiones T06

**Alcance:** recopilación de A–F y nuevas campañas de concurrencia para 2, 4 y 8 workers.
**Driver de referencia histórico:** `python-oracledb 26.1.0` Thin, `OracleClient` 1.6.2. No valida aún la versión 1.2.1.

## Entrega y seguridad

El paquete añade archivos nuevos en `scripts/`, `tests/`, `docs/` y `data/t06_historico/`. **No reemplaza** `main.py`, `oracle_client.py`, `config/`, `gunicorn.conf.py`, `run_monitor.py`, `test_concurrency.py` ni `analyze_t06.py`.

No contiene contraseñas. No crea tablas ni objetos Oracle. La carga de T06 usa el endpoint ya validado `POST /api/v1/lab/concurrency/hold`; las peticiones se envían solo a `127.0.0.1:8010`. El monitor usa una cuenta distinta de la API. No ejecutar estas pruebas en producción o sistemas clínicos compartidos sin autorización.

## 1. Instalar

Desde el **directorio padre** de `FastAPI_Oracle_Lab`:

```bash
cd ~/Proyectos
unzip -n FastAPI_Oracle_Lab_T06_Consolidado_Repeticiones.zip
cd FastAPI_Oracle_Lab
source .venv/bin/activate
```

Si ya existen ficheros con los mismos nombres, revisa el contenido antes de sobrescribirlos. Este paquete no debería colisionar con los archivos de F6/F7 anteriores.

## 2. Regenerar informe consolidado sin Oracle

```bash
python scripts/consolidate_t06.py
```

Genera `reports/consolidado/T06/` con:

- `informe_consolidado.md`: conclusiones y tablas, distinguiendo evidencia automática y manual.
- `campanas.csv`: una fila por campaña, preparada para comparar en Excel/LibreOffice.
- `grupos.csv`: agrupación de campañas comparables.
- `consolidado.json`: datos estructurados y estadísticos descriptivos.

Se leen primero los `reports/resultados/RUN_ID/report.json` locales. Si faltan históricos A–F, el paquete incluye copias en `data/t06_historico/`. **Un `run_id` solo aparece una vez**: si está en ambas ubicaciones, gana el informe local.

Para usar únicamente informes locales:

```bash
python scripts/consolidate_t06.py --no-bundled-history
```

El documento estático `docs/consolidado_A_F/informe_consolidado.md` es una instantánea reproducible de los seis archivos que proporcionaste. No incorpora resultados futuros ni sustituye al informe regenerado en tu equipo.

## 3. Preparar repeticiones: DRY RUN

Comprueba que **el Gunicorn anterior esté detenido** (Ctrl+C en su terminal). El automatizador no usa un servidor existente: exige el puerto `127.0.0.1:8010` libre y arranca/detiene su propio proceso maestro.

```bash
python scripts/run_t06_repetitions.py --dry-run
```

La configuración predeterminada produce 9 campañas nuevas: 3 con 2 workers, 3 con 4 y 3 con 8, todas con concurrencia 12, 24 peticiones, 3 segundos de espera Oracle y monitorización de 240 segundos. El monitor de cada campaña se ejecuta **antes de lanzar la carga** y continúa hasta completar su ventana, de modo que se capture la liberación por inactividad. Nueve monitores de 240 segundos requieren **36 minutos de muestreo**, además del arranque y las operaciones de carga; el propio programa se ejecuta y termina en tu máquina.

## 4. Ejecutar las nueve campañas

```bash
python scripts/run_t06_repetitions.py \
  --workers 2,4,8 \
  --repeats 3 \
  --concurrency 12 \
  --requests 24 \
  --seconds 3 \
  --monitor-duration 240 \
  --monitor-interval 1 \
  --http-samples 8 \
  --prefix LAB_T06_R_20261030
```

La opción `--prefix` debe ser **nueva** si ya has ejecutado una serie. No se sobrescriben resultados preexistentes. También se puede ejecutar un ensayo aislado con `--workers 2 --repeats 1 --prefix LAB_T06_PRUEBA_<FECHA>`.

Para cada escenario el automatizador:

1. Arranca Gunicorn con el número de workers especificado y comprueba sus procesos y `/health`.
2. Lanza `run_monitor.py` y espera una muestra de Oracle válida (`status=OK`); un error no se trata como cero sesiones.
3. Lanza `test_concurrency.py` con `run_id` propio y captura la salida y el código de retorno.
4. Mantiene el monitor hasta completar 240 segundos; no inicia una campaña nueva mientras el monitor previo siga activo.
5. Ejecuta `analyze_t06.py`, guarda `campaign.json` con el número de workers **configurado** y comprueba `APTO_PRELIMINAR`, errores cero y última muestra con cero sesiones.
6. Al cambiar de escenario, detiene **solo el Gunicorn que ha creado**, mediante SIGINT al grupo de procesos. Conserva los logs incluso si el ensayo se interrumpe.
7. Cuando todas terminan, ejecuta `consolidate_t06.py` para reunir históricos y repeticiones.

**Si ocurre un fallo:** el programa interrumpe las campañas pendientes, registra el motivo, cierra los procesos que haya creado y conserva los datos parciales; no los clasifica como APTO. Con `Ctrl+C` realiza el mismo intento de limpieza. No arranques dos automatizadores simultáneamente.

## 5. Archivos generados

Cada repetición genera:

```text
reports/
  sesiones/RUN_ID/{oracle_totals.csv,oracle_sessions.csv,pool_samples.csv,processes.csv,monitor_meta.json}
  rendimiento/RUN_ID/{requests.csv,summary.json}
  resultados/RUN_ID/{report.md,report.json,campaign.json}
  automatizacion/PREFIX/{gunicorn_W2.log,gunicorn_W4.log,gunicorn_W8.log,RUN_ID/monitor.log,RUN_ID/carga.log,RUN_ID/analisis.log,consolidacion.log}
  consolidado/T06/{informe_consolidado.md,campanas.csv,grupos.csv,consolidado.json}
```

## 6. Interpretación de la comparación

Se agrupan solo campañas con la misma **versión de `python-oracledb`**, concurrencia HTTP, número de solicitudes y duración Oracle. El consolidado calcula media, mediana y desviación típica de P95 (cuando hay más de una muestra) y picos de sesiones, además de registrar la última muestra de cada campaña.

- No sumar los picos de `busy` muestreados por worker como si fueran simultáneos.
- No deducir el número de workers configurados a partir de `requests_by_pid`; el automatizador escribe `campaign.json`.
- Un buen P95 en una campaña no basta para declarar un número óptimo de workers.
- Los nueve ensayos automatizados prueban un patrón de espera Oracle (`DBMS_SESSION.SLEEP`), no el flujo real de cámaras de producción.
- La migración comparativa al driver `python-oracledb 1.2.1` requiere preparar un entorno aparte sin modificar el cliente del laboratorio ni asumir compatibilidad con Python 3.14.

## 7. Pruebas offline

```bash
python -m unittest discover -s tests -p test_t06_tools.py -v
python -m py_compile scripts/run_t06_repetitions.py scripts/consolidate_t06.py
```

No requieren Oracle, conexión HTTP ni credenciales.
