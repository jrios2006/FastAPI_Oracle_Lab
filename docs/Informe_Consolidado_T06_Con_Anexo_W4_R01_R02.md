# FastAPI_Oracle_Lab — Informe consolidado F5/F6/F7-T06

**Generado:** 2026-10-30T20:01:20+00:00  
**Campañas incluidas:** 15. **Fuentes:** `report.json` de cada campaña y, para el Anexo A, los CSV individuales `requests.csv` y `oracle_totals.csv` de W4-R01 y W4-R02.

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
| LAB_T06_R_20261030_W2_R01 | 2 | 26.1.0 | 12 | 24/24 | 6287.13 | 3261.69 | 9 | 9 | 0 | APTO_PRELIMINAR |
| LAB_T06_R_20261030_W2_R02 | 2 | 26.1.0 | 12 | 24/24 | 6274.07 | 3105.20 | 10 | 10 | 0 | APTO_PRELIMINAR |
| LAB_T06_R_20261030_W2_R03 | 2 | 26.1.0 | 12 | 24/24 | 6225.04 | 3095.18 | 10 | 10 | 0 | APTO_PRELIMINAR |
| LAB_T06_R_20261030_W4_R01 | 4 | 26.1.0 | 12 | 24/24 | 3581.80 | 2771.44 | 17 | 12 | 0 | APTO_PRELIMINAR |
| LAB_T06_R_20261030_W4_R02 | 4 | 26.1.0 | 12 | 24/24 | 6284.03 | 3227.02 | 12 | 9 | 0 | APTO_PRELIMINAR |
| LAB_T06_R_20261030_W4_R03 | 4 | 26.1.0 | 12 | 24/24 | 3503.82 | 3106.75 | 16 | 12 | 0 | APTO_PRELIMINAR |
| LAB_T06_R_20261030_W8_R01 | 8 | 26.1.0 | 12 | 24/24 | 3414.50 | 390.22 | 18 | 12 | 0 | APTO_PRELIMINAR |
| LAB_T06_R_20261030_W8_R02 | 8 | 26.1.0 | 12 | 24/24 | 3373.15 | 2883.36 | 17 | 12 | 0 | APTO_PRELIMINAR |
| LAB_T06_R_20261030_W8_R03 | 8 | 26.1.0 | 12 | 24/24 | 3266.09 | 183.72 | 18 | 12 | 0 | APTO_PRELIMINAR |

## 3. Comparaciones homogéneas y repeticiones

Solo se agrupan campañas con **igual** versión del driver, número de workers, concurrencia HTTP, solicitudes y duración Oracle.
La mediana y desviación típica son descriptivas; con menos de tres repeticiones no sirven para certificar una diferencia de rendimiento.

| Driver | Workers | Concurrencia | Solicitudes | Reps. | Mediana P95 (ms) | Desv. típica P95 (ms) | Pico sesiones | Finales a cero |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 26.1.0 | 2 | 4 | 12 | 2 | 3175.47 | 144.58 | 5 | 1/2 |
| 26.1.0 | 2 | 8 | 24 | 1 | 3435.75 | ND | 9 | 1/1 |
| 26.1.0 | 2 | 12 | 24 | 4 | 6249.56 | 33.92 | 10 | 4/4 |
| 26.1.0 | 4 | 12 | 24 | 4 | 4777.87 | 1498.82 | 17 | 4/4 |
| 26.1.0 | 8 | 12 | 24 | 4 | 3373.63 | 63.57 | 18 | 4/4 |

## 4. Lectura técnica

- Las campañas B–F observaron cero sesiones en su última muestra y ausencia de infracciones de pool en los informes disponibles.
- La campaña A terminó con cinco sesiones en la última muestra (`INCONCLUSO_O_REVISAR`); después se verificó manualmente ausencia de sesiones y `opened=0` en ambos pools, **fuera del periodo del monitor**.
- En D (2 workers, concurrencia 12), ambos pools alcanzaron cinco conexiones; las esperas de adquisición y P95 fueron altas.
- E (4 workers, misma carga) no mejoró sustancialmente frente a D en una sola campaña; hubo reparto desigual de peticiones.
- F (8 workers, misma carga) presentó menor P95 y menor espera máxima; es un **resultado de una muestra**, no una garantía de escalado.
- La existencia de 18 sesiones físicas con concurrencia HTTP 12 es compatible con conexiones inactivas retenidas temporalmente por los pools.
- La variabilidad entre W4-R01 y W4-R02 se analiza en el **Anexo A**, con las distribuciones temporales por PID y las esperas de adquisición medidas en cada petición.

## 5. Criterios y limitaciones

- `APTO_PRELIMINAR` es el estado del analizador, no una certificación de producción ni de ausencia universal de fugas.
- Una última muestra con cero sesiones no prueba el comportamiento de todas las ejecuciones futuras.
- Los diagnósticos de pool por HTTP son muestras aleatorias de workers; `peak_busy_observed` es un pico individual y **no** representa el máximo agregado simultáneo.
- `DBMS_SESSION.SLEEP` no reproduce la lógica clínica real, los procedimientos originales ni los diferentes tiempos WAN de producción.
- Las comparaciones de rendimiento deben repetirse y documentar distribución temporal, driver, servidor Oracle y presión externa.
- La comparación con `python-oracledb` 1.2.1 está **pendiente**; no se ha establecido que el driver explique las 40 sesiones de `pisuerga`.

## 6. Estado de ensayos y siguientes pasos

1. **Completado:** tres repeticiones adicionales por configuración (2/4/8 workers; concurrencia 12, 24 solicitudes, 3 segundos), junto a las campañas históricas D/E/F.
2. **Completado:** monitorización completa de 240 segundos por repetición y resultados con `run_id` único.
3. **Analizado:** dispersión de P95 y esperas; la diferencia W4-R01/R02 queda documentada en el **Anexo A**.
4. **Pendiente:** planificar la comparación de versiones del driver en entornos equivalentes y sin modificar `OracleClient` original.

## 7. Procedencia de datos

- `LAB_T06_20261030_A`: `reports/resultados/LAB_T06_20261030_A/report.json`
- `LAB_T06_20261030_B`: `reports/resultados/LAB_T06_20261030_B/report.json`
- `LAB_T06_20261030_C`: `reports/resultados/LAB_T06_20261030_C/report.json`
- `LAB_T06_20261030_D`: `reports/resultados/LAB_T06_20261030_D/report.json`
- `LAB_T06_20261030_E`: `reports/resultados/LAB_T06_20261030_E/report.json`
- `LAB_T06_20261030_F`: `reports/resultados/LAB_T06_20261030_F/report.json`
- `LAB_T06_R_20261030_W2_R01`: `reports/resultados/LAB_T06_R_20261030_W2_R01/report.json`
- `LAB_T06_R_20261030_W2_R02`: `reports/resultados/LAB_T06_R_20261030_W2_R02/report.json`
- `LAB_T06_R_20261030_W2_R03`: `reports/resultados/LAB_T06_R_20261030_W2_R03/report.json`
- `LAB_T06_R_20261030_W4_R01`: `reports/resultados/LAB_T06_R_20261030_W4_R01/report.json`
- `LAB_T06_R_20261030_W4_R02`: `reports/resultados/LAB_T06_R_20261030_W4_R02/report.json`
- `LAB_T06_R_20261030_W4_R03`: `reports/resultados/LAB_T06_R_20261030_W4_R03/report.json`
- `LAB_T06_R_20261030_W8_R01`: `reports/resultados/LAB_T06_R_20261030_W8_R01/report.json`
- `LAB_T06_R_20261030_W8_R02`: `reports/resultados/LAB_T06_R_20261030_W8_R02/report.json`
- `LAB_T06_R_20261030_W8_R03`: `reports/resultados/LAB_T06_R_20261030_W8_R03/report.json`

---

<!-- T06_ANEXO_W4_R01_R02_INICIO -->

## Anexo A. Análisis de la variabilidad W4-R01 frente a W4-R02

**Objeto.** Explicar la diferencia observada en la latencia P95 de las campañas `LAB_T06_R_20261030_W4_R01` y `LAB_T06_R_20261030_W4_R02`, ambas con 4 workers Gunicorn, `pool_max=5` por worker, concurrencia HTTP 12, 24 peticiones y `DBMS_SESSION.SLEEP(3)`.

**Alcance de la evidencia.** Se han contrastado los 24 registros de `requests.csv` y las 240 muestras de `oracle_totals.csv` de cada campaña, junto con sus `report.json`. Los cálculos de medias, distribución por PID y solicitudes superiores a 5 segundos proceden de los CSV por petición. Las latencias P95 son las consignadas en los informes de campaña. La etiqueta `APTO_PRELIMINAR` no equivale a una certificación para producción.

### A.1. Comparación cuantitativa

| Indicador | W4-R01 | W4-R02 |
|---|---:|---:|
| Solicitudes correctas | 24/24 | 24/24 |
| Duración total del escenario | 9,357 s | 12,270 s |
| Latencia HTTP P95 (informe) | 3.581,80 ms | **6.284,03 ms** |
| Espera media de adquisición del pool | 253,33 ms | **1.117,56 ms** |
| Espera máxima de adquisición del pool | 2.771,44 ms | **3.227,02 ms** |
| Duración media de la operación Oracle | 3.021,01 ms | 3.022,25 ms |
| Solicitudes HTTP con duración > 5.000 ms | 1 | **8** |
| Pico de sesiones Oracle | 17 | 12 |
| Pico de sesiones ACTIVE | 12 | 9 |
| Muestras Oracle válidas / errores | 240 / 0 | 240 / 0 |
| Sesiones en la última muestra | **0** | **0** |

El P95 subió aproximadamente **75,4 %** en R02 frente a R01, mientras que la duración media de la llamada Oracle permaneció prácticamente igual (diferencia aproximada de 1,24 ms). La espera media de adquisición aumentó unos **864 ms**. Por tanto, los datos señalan la espera para adquirir una conexión como principal componente del deterioro, no una ejecución Oracle sensiblemente más lenta.

### A.2. Distribución de las 24 peticiones

| PID del worker | W4-R01 | W4-R02 |
|---|---:|---:|
| `30875` | 8 | **16** |
| `30877` | 6 | 5 |
| `30878` | 7 | 2 |
| `30879` | 3 | 1 |
| **Total** | **24** | **24** |

En R01, el worker más utilizado atendió 8 solicitudes (33,3 %). En R02, el PID `30875` atendió **16 de 24 (66,7 %)**. Dado que los pools Oracle se crean por worker y no se comparten entre procesos, la capacidad global teórica de 20 conexiones no evita que un solo pool de cinco conexiones se quede sin disponibilidad temporal.

### A.3. Concentración en la primera oleada

Las primeras 12 solicitudes se han identificado **ordenando `inicio_utc`**, no asumiendo que el campo `index` coincide necesariamente con el orden real de inicio.

| PID del worker | Primera oleada W4-R01 | Primera oleada W4-R02 |
|---|---:|---:|
| `30875` | 2 | **8** |
| `30877` | 2 | 1 |
| `30878` | 5 | 2 |
| `30879` | 3 | 1 |
| **Total** | **12** | **12** |

En R02, ocho solicitudes iniciadas en un intervalo de unas décimas de segundo quedaron asignadas al PID `30875`, cuyo pool admite como máximo cinco conexiones físicas. Las peticiones de índice **6, 7 y 11** registraron esperas de adquisición de **3.227,02 ms**, **3.086,74 ms** y **3.155,87 ms**, respectivamente. Son compatibles con una segunda tanda que debe aguardar la liberación de conexiones ocupadas durante tres segundos.

En R01, el máximo de solicitudes asignadas a un mismo PID en la primera oleada fue cinco y ninguna de esas primeras 12 solicitudes superó cinco segundos de duración HTTP.

### A.4. Peticiones lentas y desglose temporal

En R01 únicamente la petición **23** superó 5.000 ms: PID `30875`, duración HTTP **5.813,74 ms**, de los cuales **2.771,44 ms** correspondieron a la espera del pool.

En R02, las peticiones de índice **6, 7, 11, 17, 19, 20, 21 y 24** superaron 5.000 ms. **Las ocho fueron atendidas por el PID `30875`** y sus esperas del pool oscilaron entre **2.932,37 y 3.227,02 ms**. La mayor duración HTTP fue **6.339,19 ms** (petición 6), con **3.227,02 ms** de espera para adquirir conexión y **3.014,49 ms** de operación Oracle.

La coincidencia entre la concentración de solicitudes en un único PID, las esperas cercanas a tres segundos y la duración estable de la operación Oracle constituye evidencia directa de **contención local en el pool de ese worker**. El recuento de peticiones por PID, por sí solo, no bastaría: esta interpretación se apoya también en el solapamiento temporal y en las duraciones individuales.

### A.5. Comportamiento de las sesiones Oracle después de la carga

| Comprobación | W4-R01 | W4-R02 |
|---|---:|---:|
| Máximo de sesiones totales | 17 | 12 |
| Máximo de sesiones ACTIVE | 12 | 9 |
| Primera muestra con cero sesiones **después de terminar la última petición** | Muestra 128 | Muestra 127 |
| Tiempo hasta esa muestra desde el fin de la última petición | ~116,86 s | ~113,32 s |
| Última muestra (239) | 0 sesiones | 0 sesiones |
| Errores registrados en el monitor | 0 | 0 |

Las muestras verifican que las sesiones físicas se liberaron durante el periodo de observación. No se registraron sesiones residuales en la última muestra de ninguna de las dos campañas. El tiempo hasta la primera muestra con cero sesiones es **aproximado** y depende de la resolución temporal del muestreo; no representa el instante exacto del cierre de cada conexión.

### A.6. Diagnóstico y límites de la explicación

**Diagnóstico respaldado por las mediciones:** la peor latencia de W4-R02 se explica principalmente por **un reparto desigual de las solicitudes HTTP que saturó temporalmente el pool independiente del PID `30875`**, mientras otros workers recibían menos peticiones. No se observa ralentización significativa de la operación Oracle ni retención persistente de sesiones al cierre de la campaña.

**Aspecto no demostrado:** estos archivos no permiten determinar **por qué** Gunicorn o la capa de transporte asignaron las conexiones HTTP de esa forma. La distribución puede verse afectada por la aceptación de conexiones TCP, planificación de procesos o reutilización de conexiones, entre otros factores; identificar el mecanismo requiere nuevas mediciones y no se atribuye a una causa concreta en este informe.

**Alcance:** prueba sintética con `DBMS_SESSION.SLEEP` y `python-oracledb` 26.1.0 Thin. No demuestra comportamiento idéntico en la aplicación real ni descarta problemas específicos de `python-oracledb` 1.2.1.

### A.7. Fuentes y trazabilidad

- `reports/rendimiento/LAB_T06_R_20261030_W4_R01/requests.csv`
- `reports/rendimiento/LAB_T06_R_20261030_W4_R02/requests.csv`
- `reports/sesiones/LAB_T06_R_20261030_W4_R01/oracle_totals.csv`
- `reports/sesiones/LAB_T06_R_20261030_W4_R02/oracle_totals.csv`
- `reports/resultados/LAB_T06_R_20261030_W4_R01/report.json`
- `reports/resultados/LAB_T06_R_20261030_W4_R02/report.json`

**Recomendación:** conservar este anexo junto al consolidado y tener en cuenta la distribución temporal por worker al comparar el número de procesos; no interpretar la capacidad agregada de los pools como si fuese compartida entre todos los workers.

<!-- T06_ANEXO_W4_R01_R02_FIN -->
