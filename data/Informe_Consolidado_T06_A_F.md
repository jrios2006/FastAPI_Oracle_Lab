# FastAPI_Oracle_Lab — Informe consolidado F5/F6/F7-T06

**Generado:** 2026-10-30T19:17:08+00:00  
**Campañas incluidas:** 6. **Fuente:** `report.json` de cada campaña.

## 1. Alcance y método

- Laboratorio Oracle 19c, FastAPI/Gunicorn, `OracleClient` 1.6.2 sin modificaciones, `python-oracledb` 26.1.0 Thin (campañas históricas A–F).
- F5: los escenarios secuenciales de 1, 2, 4 y 8 workers se validaron manualmente en la conversación; no hay métricas F5 normalizadas en estos `report.json`.
- F6: monitor externo de `V$SESSION` separado de la cuenta de API; F7/T06: `DBMS_SESSION.SLEEP` bloquea una conexión en cada solicitud.
- Los picos son máximos de muestras, no sumas de máximos por PID tomadas en instantes distintos.
- `pool_max=5` es un límite por worker, no por servidor Gunicorn completo.

## 2. Campañas individuales

| Campaña | Workers | Driver | HTTP conc. | Correctas | P95 (ms) | Espera máx. pool (ms) | Sesiones pico | ACTIVE pico | Sesiones finales | Estado |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| LAB_T06_20261030_A | 2 | 26.1.0 | 4 | 12/12 | 3277.71 | 205.37 | 5 | 4 | 5 | INCONCLUSO_O_REVISAR |
| LAB_T06_20261030_B | 2 | 26.1.0 | 4 | 12/12 | 3073.24 | 1.64 | 5 | 4 | 0 | APTO_PRELIMINAR |
| LAB_T06_20261030_C | 2 | 26.1.0 | 8 | 24/24 | 3435.75 | 365.58 | 9 | 8 | 0 | APTO_PRELIMINAR |
| LAB_T06_20261030_D | 2 | 26.1.0 | 12 | 24/24 | 6220.31 | 3182.94 | 10 | 10 | 0 | APTO_PRELIMINAR |
| LAB_T06_20261030_E | 4 | 26.1.0 | 12 | 24/24 | 5973.94 | 3082.79 | 15 | 11 | 0 | APTO_PRELIMINAR |
| LAB_T06_20261030_F | 8 | 26.1.0 | 12 | 24/24 | 3374.11 | 259.06 | 18 | 12 | 0 | APTO_PRELIMINAR |

## 3. Comparaciones homogéneas y repeticiones

Solo se agrupan campañas con **igual** versión del driver, número de workers, concurrencia HTTP, solicitudes y duración Oracle.
La mediana y desviación típica son descriptivas; con menos de tres repeticiones no sirven para certificar una diferencia de rendimiento.

| Driver | Workers | Concurrencia | Solicitudes | Reps. | Mediana P95 (ms) | Desv. típica P95 (ms) | Pico sesiones | Finales a cero |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 26.1.0 | 2 | 4 | 12 | 2 | 3175.47 | 144.58 | 5 | 1/2 |
| 26.1.0 | 2 | 8 | 24 | 1 | 3435.75 | ND | 9 | 1/1 |
| 26.1.0 | 2 | 12 | 24 | 1 | 6220.31 | ND | 10 | 1/1 |
| 26.1.0 | 4 | 12 | 24 | 1 | 5973.94 | ND | 15 | 1/1 |
| 26.1.0 | 8 | 12 | 24 | 1 | 3374.11 | ND | 18 | 1/1 |

## 4. Lectura técnica

- Las campañas B–F observaron cero sesiones en su última muestra y ausencia de infracciones de pool en los informes disponibles.
- La campaña A terminó con cinco sesiones en la última muestra (`INCONCLUSO_O_REVISAR`); después se verificó manualmente ausencia de sesiones y `opened=0` en ambos pools, **fuera del periodo del monitor**.
- En D (2 workers, concurrencia 12), ambos pools alcanzaron cinco conexiones; las esperas de adquisición y P95 fueron altas.
- E (4 workers, misma carga) no mejoró sustancialmente frente a D en una sola campaña; hubo reparto desigual de peticiones.
- F (8 workers, misma carga) presentó menor P95 y menor espera máxima; es un **resultado de una muestra**, no una garantía de escalado.
- La existencia de 18 sesiones físicas con concurrencia HTTP 12 es compatible con conexiones inactivas retenidas temporalmente por los pools.

## 5. Criterios y limitaciones

- `APTO_PRELIMINAR` es el estado del analizador, no una certificación de producción ni de ausencia universal de fugas.
- Una última muestra con cero sesiones no prueba el comportamiento de todas las ejecuciones futuras.
- Los diagnósticos de pool por HTTP son muestras aleatorias de workers; `peak_busy_observed` es un pico individual y **no** representa el máximo agregado simultáneo.
- `DBMS_SESSION.SLEEP` no reproduce la lógica clínica real, los procedimientos originales ni los diferentes tiempos WAN de producción.
- Las comparaciones de rendimiento deben repetirse y documentar distribución temporal, driver, servidor Oracle y presión externa.
- La comparación con `python-oracledb` 1.2.1 está **pendiente**; no se ha establecido que el driver explique las 40 sesiones de `pisuerga`.

## 6. Próximos ensayos

1. Ejecutar al menos tres repeticiones por configuración (2/4/8 workers; concurrencia 12, 24 solicitudes, 3 segundos).
2. Exigir monitorización completa de 240 segundos por repetición y guardar sus archivos por `run_id` único.
3. Analizar dispersión de P95, espera máxima y picos por worker; no elegir configuración a partir de una sola campaña.
4. Planificar comparación de versiones del driver en entornos equivalentes y sin modificar `OracleClient` original.

## 7. Procedencia de datos

- `LAB_T06_20261030_A`: `data/t06_historico/LAB_T06_20261030_A/report.json`
- `LAB_T06_20261030_B`: `data/t06_historico/LAB_T06_20261030_B/report.json`
- `LAB_T06_20261030_C`: `data/t06_historico/LAB_T06_20261030_C/report.json`
- `LAB_T06_20261030_D`: `data/t06_historico/LAB_T06_20261030_D/report.json`
- `LAB_T06_20261030_E`: `data/t06_historico/LAB_T06_20261030_E/report.json`
- `LAB_T06_20261030_F`: `data/t06_historico/LAB_T06_20261030_F/report.json`
