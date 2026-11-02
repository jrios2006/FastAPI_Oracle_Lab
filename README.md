# FastAPI Oracle Lab

**Documento funcional y plan de implementación**  
**Estado:** referencia funcional aprobada; F1/F2 validadas; F3/F4 implementadas y pendientes de prueba Oracle real (versión 0.2)  
**Fecha:** 30/10/2026  
**Nombre del proyecto:** `FastAPI_Oracle_Lab`

## 1. Finalidad

Construir un laboratorio **independiente** de `Backend_Oracle` para estudiar, medir y validar el comportamiento de **FastAPI**, **Uvicorn**, **Gunicorn** y la biblioteca existente **`oracle_client.py` (versión de partida 1.6.2)** al acceder a **Oracle 19c**.

La finalidad principal **no** es certificar el CRUD por sí mismo, sino responder con mediciones reproducibles a estas preguntas:

1. ¿Cuántos pools y conexiones físicas Oracle se crean por proceso worker?
2. ¿Las conexiones se devuelven al pool después de cada operación?
3. ¿Las conexiones inactivas se liberan con `pool_min=0` y `timeout` configurado?
4. ¿El pool puede crear nuevas conexiones tras quedarse sin conexiones físicas abiertas?
5. ¿Los límites de conexiones se respetan con peticiones concurrentes y múltiples workers?
6. ¿El procedimiento almacenado, las transacciones y los errores se comportan correctamente?
7. ¿Los recursos se cierran correctamente cuando finalizan los workers?
8. ¿Qué cambia entre Uvicorn y Gunicorn, y entre modo Thin y Thick de `python-oracledb` si se ensayan ambos?

El laboratorio no se integrará en el backend principal ni alterará sus tablas o procedimientos.

## 2. Alcance y exclusiones

**Incluye:**

- Aplicación FastAPI de pruebas, con ciclo de vida explícito.
- Uso inicial de una copia **sin cambios funcionales** del `oracle_client.py` actual.
- Una tabla Oracle y un procedimiento almacenado específicos del laboratorio.
- CRUD HTTP completo y endpoint para invocar el procedimiento.
- Diagnóstico del pool desde cada worker, con identificación inequívoca del proceso.
- Monitor Oracle externo e independiente del pool sometido a prueba.
- Ensayos de actividad, inactividad, recuperación, concurrencia, transacciones y apagado.
- Registro de resultados y comparación con criterios de aceptación.

**Excluye:**

- Modificaciones en `Backend_Oracle` durante el desarrollo del laboratorio.
- Datos clínicos o reales; solo datos sintéticos.
- Servicios SFTP, autenticación de negocio y cronjobs de fotografías.
- Creación de pools dentro de cada petición HTTP como implementación definitiva. Ese antipatrón podrá estudiarse únicamente en una prueba aislada posterior y explícita.
- Reintentos automáticos que oculten fallos de conectividad en los informes.

## 3. Principios de diseño

1. **Aislamiento:** objetos, credenciales, identificadores de sesión, puertos y registros diferenciados del sistema existente.
2. **Línea base reproducible:** conservar `oracle_client.py` 1.6.2 sin cambios inicialmente; documentar su hash y las dependencias instaladas.
3. **Una instancia del servicio y un pool por worker:** creados después de la creación del proceso worker; reutilizados durante las peticiones de ese worker; cerrados en su apagado.
4. **Separación de papeles:** el monitor usa una conexión/credencial propia y nunca se integra en el pool de prueba.
5. **Trazabilidad:** todas las operaciones y medidas se vinculan con `run_id`, marca de tiempo UTC, PID del worker y, cuando proceda, ID de operación.
6. **Observabilidad dual:** cotejar métricas del pool (`opened`, `busy`) y sesiones físicas de Oracle (`V$SESSION` o vista disponible).
7. **Sin cambios silenciosos:** toda modificación de configuración, driver o código da lugar a una ejecución identificada y comparable.
8. **Seguridad:** secretos fuera de Git; endpoints de diagnóstico limitados a localhost o red de laboratorio y sin publicación pública.

## 4. Estructura obligatoria de archivos

```text
FastAPI_Oracle_Lab/
├── README.md
├── main.py
├── gunicorn.conf.py
├── requirements.txt
├── .gitignore
│
├── config/
│   ├── config.json
│   ├── credenciales.json
│   ├── credenciales.example.json
│   └── sql/
│       ├── 01_instalacion.sql
│       ├── 02_consultas_monitor.sql
│       └── 03_desinstalacion.sql
│
├── module/
│   ├── __init__.py
│   ├── oracle_client.py
│   ├── config_loader.py
│   ├── test_service.py
│   └── diagnostics_service.py
│
├── utils/
│   ├── __init__.py
│   └── logger.py
│
├── router/
│   ├── __init__.py
│   ├── test_api.py
│   └── diagnostics_api.py
│
├── monitoring/
│   ├── __init__.py
│   ├── oracle_monitor.py
│   ├── process_monitor.py
│   └── metrics_collector.py
│
├── tests/
│   ├── test_crud.py
│   ├── test_procedure.py
│   ├── test_pool_idle.py
│   ├── test_concurrency.py
│   └── test_recovery.py
│
├── scripts/
│   ├── start_uvicorn.sh
│   ├── start_gunicorn.sh
│   ├── validar_conexiones.py
│   └── run_monitor.py
│
├── reports/
│   ├── sesiones/
│   ├── rendimiento/
│   └── resultados/
│
└── logs/
```

El módulo `utils/logger.py` adapta el logger 1.2.0 del backend para registrar PID y marca UTC, conservar los logs de Uvicorn/Gunicorn y evitar que varios workers roten el mismo archivo. `utils/__init__.py` declara el paquete.

Los archivos `reports/` y `logs/` son directorios de salida; no se versionan los resultados ni los secretos. No se crearán archivos adicionales sin actualizar primero este inventario.

## 5. Contrato de base de datos Oracle

### 5.1. Instalación y limpieza

- `config/sql/01_instalacion.sql`: crea **una única tabla** y **un procedimiento** de laboratorio; define restricciones e índices imprescindibles.
- `config/sql/02_consultas_monitor.sql`: recopila las consultas de seguimiento de sesiones, procesos y límites de Oracle. Las vistas de administración requieren permisos específicos de solo lectura.
- `config/sql/03_desinstalacion.sql`: elimina únicamente los objetos del laboratorio y deja intactos los demás objetos del esquema.
- La instalación y la desinstalación se ejecutan **manualmente**, desde DBeaver o herramienta SQL autorizada; la API no crea ni elimina estructura automáticamente.

### 5.2. Objetos definidos

**Tabla:** `LAB_POOL_REGISTROS`.

| Columna | Tipo lógico | Finalidad |
|---|---|---|
| `ID` | Identidad numérica | Clave primaria |
| `RUN_ID` | Cadena identificadora | Campaña/ejecución de prueba |
| `CODIGO` | Cadena | Clave funcional de registro |
| `DESCRIPCION` | Cadena | Texto modificable por CRUD |
| `VALOR` | Número | Campo para operaciones y pruebas transaccionales |
| `ESTADO` | Cadena | Estado funcional del registro |
| `FCREACION` | Fecha/hora | Alta del registro |
| `FMODIFICACION` | Fecha/hora nullable | Última modificación |

**Procedimiento:** `SP_LAB_POOL_OPERACION`.

Contrato funcional:

- Recibe el identificador de un registro, el nuevo valor numérico y el identificador de ejecución.
- Comprueba que existe el registro y que pertenece a la ejecución indicada.
- Actualiza su valor y fecha de modificación.
- Devuelve el resultado funcional de la operación mediante parámetros de salida definidos en la implementación SQL.
- Ante datos inválidos, genera un error Oracle identificable para verificar propagación de fallos.
- **No hace `COMMIT` ni `ROLLBACK`:** la transacción queda bajo el control de `OracleClient`/servicio para poder medir y comparar el comportamiento existente.

Todos los datos serán sintéticos. La eliminación del CRUD será lógica o física según se cierre en la implementación de `test_service.py`; para esta versión **se define DELETE físico limitado al `RUN_ID` de la campaña**. La tabla nunca se vaciará indiscriminadamente mediante una petición HTTP.

## 6. Contrato de API

**Prefijo:** `/api/v1/lab`.

| Método | Ruta | Operación | Acceso Oracle |
|---|---|---|---|
| `POST` | `/registros` | Crear registro | `execute_dml()` |
| `GET` | `/registros` | Listar registros de un `run_id` | `execute_query_json()` |
| `GET` | `/registros/{id}` | Consultar registro | `execute_query_json()` |
| `PUT` | `/registros/{id}` | Actualizar registro | `execute_dml()` |
| `DELETE` | `/registros/{id}` | Eliminar registro del `run_id` | `execute_dml()` |
| `POST` | `/registros/{id}/procedimiento` | Ejecutar procedimiento Oracle | `call_procedure...()` según parámetros OUT |
| `GET` | `/health` | Salud del proceso FastAPI, sin Oracle | Ninguno |
| `GET` | `/diagnostics/worker` | PID, PPID, versión de driver, modo Thin/Thick, identificador del worker | Ninguno |
| `GET` | `/diagnostics/pool` | Estado del pool del worker que atiende la petición | Métricas internas, sin adquirir conexión |

Las rutas CRUD devolverán estados HTTP coherentes (`2xx`, `404`, `409`, `422` y `5xx`, según corresponda). Los errores Oracle deben registrarse con causa técnica en logs, sin exponer contraseñas o información de conexión en respuestas públicas.

**Importante en multiworker:** una petición a `/diagnostics/pool` observa **solo el worker que responde**, no todos los workers. Para una vista global se recopilarán las muestras por PID desde logs y el monitor externo; no se inferirá la situación de todos los procesos a partir de una sola petición.

## 7. Diseño de los servicios y del pool

### `module/oracle_client.py`

- Primera versión: copia sin modificaciones funcionales de `OracleClient` 1.6.2.
- Parámetros configurables desde `config/config.json`: `pool_min`, `pool_max`, `retry`, `timeout` y valores de espera compatibles con el modo de adquisición utilizado.
- Se registrarán versión de `python-oracledb`, modo Thin/Thick y versión de cliente Oracle si corresponde.
- La revisión de posibles mejoras del cliente se hará **después** de obtener la línea base; nunca mezclada con una prueba de comparación.

### `module/test_service.py`

- Implementa las seis operaciones de negocio (CRUD y procedimiento).
- No construye un `OracleClient` por solicitud.
- No cierra el pool al finalizar una operación individual.
- Se responsabiliza de devolver errores y resultados de manera verificable.

### `module/diagnostics_service.py`

- Lee métricas internas del pool con la mínima interferencia posible: `opened`, `busy`, `min`, `max`, `timeout`, identidad del pool y PID.
- Distingue claramente **pool abierto** de **conexiones físicas abiertas**.
- No adquiere conexiones Oracle únicamente para responder a métricas internas.

### `main.py`

- Gestiona el ciclo de vida (`lifespan`) por proceso worker.
- Crea y mantiene el servicio/pool después del arranque del worker; evita crear un pool en el proceso maestro antes de un `fork`.
- Cierra el pool durante el apagado ordenado, después de dejar de aceptar trabajo nuevo y terminar las operaciones en curso.
- No incorpora scheduler interno en esta primera versión.

## 8. Configuración de ejecución

### `config/config.json`

Define, como mínimo:

- Entorno de laboratorio y puerto de escucha.
- Modalidad de servidor (`uvicorn` o `gunicorn`) y número de workers.
- Parámetros del pool (`min`, `max`, `increment`, `timeout`, `retry`, política de espera).
- Intervalo de muestreo del monitor externo y duración de la fase de reposo.
- Identificadores de aplicación y de sesiones para diferenciar los pools del laboratorio de otras aplicaciones.
- Directorios de logs e informes.

### `config/credenciales.json`

Incluye dos contextos separados:

1. **Aplicación:** usuario Oracle con permisos mínimos sobre la tabla y el procedimiento del laboratorio.
2. **Monitor:** usuario con permisos **de lectura limitados** para consultar sesiones y límites de Oracle; no utiliza el pool de FastAPI.

El archivo real queda excluido de Git. `credenciales.example.json` describe únicamente los nombres de las claves.

### Validación de las credenciales y permisos (F2)

- `requirements.txt`: instala FastAPI, Uvicorn, Gunicorn, `uvicorn-worker`, `oracledb`, `charset-normalizer`, y las bibliotecas de monitorización/pruebas. La versión instalada de `oracledb` debe compararse con la del backend original antes de iniciar ensayos de equivalencia; se archivará `pip freeze` por campaña. Los rangos de versiones no sustituyen una captura reproducible de versiones exactas.
- `scripts/validar_conexiones.py`: precomprobación independiente, **solo lectura**, para `config/credenciales.json`. Usa `ConfigLoader` y las dos instancias diferenciadas de `OracleClient` (`LAB_API` y `LAB_MONITOR`).
- `LAB_API` valida autenticación, contexto `LAB_POOL_API`, acceso SELECT sin lectura de filas a `AHJPS_M.LAB_POOL_REGISTROS`, y visibilidad/validez de `SP_LAB_POOL_OPERACION`.
- `LAB_MONITOR` valida autenticación, contexto `LAB_POOL_MONITOR`, permisos SELECT en `V$SESSION` y `V$RESOURCE_LIMIT`, y visibilidad de sesiones de la API. El monitor usa otro pool y nunca adquiere conexiones del pool medido.
- El comando de validación guarda un informe JSON sin contraseñas en `reports/resultados/`. La utilidad no realiza INSERT, UPDATE, DELETE ni invocación del procedimiento.
- Los permisos del monitor sobre `SYS.V_$SESSION` y `SYS.V_$RESOURCE_LIMIT` pueden requerir concesión explícita por un DBA. Las credenciales reales permanecen exclusivamente en el equipo de ejecución.
- No se considera completa la validación hasta ejecutar el script **desde el equipo con acceso a Oracle** y obtener resultados positivos. Una comprobación estática de JSON o de sintaxis no certifica conectividad real.

### Ejecución de servidores

- `scripts/start_uvicorn.sh`: inicia la configuración monoproceso de referencia.
- `scripts/start_gunicorn.sh`: inicia Gunicorn con workers Uvicorn compatibles con las versiones instaladas.
- `gunicorn.conf.py`: controla número de workers, logs, tiempos y apagado. Debe evitarse crear conexiones Oracle en el proceso maestro antes de generar workers.
- La configuración efectiva de cada ejecución se registra en el informe (no solo la configuración deseada).

## 9. Monitorización y métricas

### 9.1. Fuentes

1. **Métricas internas por worker:** PID, identidad del pool, `opened`, `busy`, `min`, `max`, `timeout`, marca temporal.
2. **Oracle:** sesiones de laboratorio, estado (`ACTIVE`/`INACTIVE`), `SID`, `SERIAL#`, `LOGON_TIME`, `LAST_CALL_ET`, usuario, máquina, módulo e identificador de cliente.
3. **Sistema operativo:** PID, PPID, comando, hora de inicio, número de procesos y reinicios de workers.
4. **API:** ruta, método, resultado HTTP, duración, `run_id`, PID del worker y error clasificado.

`CLIENT_IDENTIFIER` y otros atributos de sesión pueden persistir al reutilizar conexiones; se deben asignar/limpiar explícitamente al adquirirlas. Se utilizará una convención exclusiva del laboratorio, sin reutilizar `THW_PHOTOS`.

### 9.2. Herramientas de monitorización

- `monitoring/oracle_monitor.py`: consulta Oracle **desde fuera de FastAPI** mediante conexión independiente, identifica sesiones del laboratorio y sus tiempos.
- `monitoring/process_monitor.py`: enumera procesos Uvicorn/Gunicorn y detecta cambios de PID.
- `monitoring/metrics_collector.py`: integra series temporales, distingue contadores acumulados y valores instantáneos, y escribe muestras por ejecución.
- `scripts/run_monitor.py`: controla la recogida periódica; no crea trabajo de carga ni utiliza el pool examinado.

### 9.3. Resultados mínimos

- CSV o JSON de muestras con UTC, `run_id`, PID, pool, conexiones abiertas, ocupadas y sesiones Oracle.
- Resumen por escenario: mínimo, máximo, media y evolución temporal; porcentaje de errores HTTP/Oracle; latencias de petición.
- Lista de excepciones, cierres, reinicios de worker y cambios de configuración.
- Comparación de sesiones antes/durante/después de actividad y tras reposo.
- Evidencia inequívoca de si un resultado corresponde al pool completo, a un worker o a una consulta puntual.

## 10. Plan de ensayos

**Condiciones generales:** todos los escenarios comienzan con una campaña nueva (`run_id`), configuración registrada, aplicación reiniciada de forma controlada cuando se requiera y monitor externo activo.

| ID | Ensayo | Objetivo |
|---|---|---|
| `T01` | Arranque sin tráfico | Detectar conexiones creadas durante startup |
| `T02` | CRUD secuencial | Verificar reutilización, devolución y transacciones |
| `T03` | Procedimiento | Verificar `call_procedure`, parámetros OUT, COMMIT y errores |
| `T04` | Reposo | Comprobar reducción de conexiones libres durante inactividad |
| `T05` | Reactivación | Comprobar solicitudes exitosas tras `opened=0` |
| `T06` | Concurrencia | Respetar `pool_max` por worker y medir esperas |
| `T07` | Multiworker | Comparar pools y sesiones con 1, 2, 4 y 8 workers |
| `T08` | Fallos controlados | Clasificar errores y recuperación sin esconder fallos |
| `T09` | Apagado/reinicio | Comprobar cierre de pools y ausencia de sesiones residuales |
| `T10` | Estabilidad prolongada | Detectar crecimiento acumulativo de recursos bajo ciclos repetidos |

Las cargas iniciales serán de lectura y después de escritura, con intensidad progresiva y límites seguros para la instancia Oracle. No se ejecutarán ensayos de saturación sin definir previamente un máximo seguro de concurrencia.

### 10.1. Ensayo de inactividad

1. Medir número de conexiones y sesiones antes de generar tráfico.
2. Generar un número definido de peticiones y comprobar que terminan.
3. Confirmar que `busy` vuelve a cero tras la carga.
4. Continuar muestreando durante el reposo, sin tráfico de la API de pruebas.
5. Comprobar si `opened` y las sesiones Oracle disminuyen; registrar tiempos reales, sin exigir que coincidan exactamente con `timeout`.
6. Emitir una nueva petición **sin reiniciar FastAPI** y verificar recuperación.
7. Repetir varios ciclos.

En caso de no disminuir a cero, se documentarán modo de driver, versión, actividad concurrente y condiciones reales antes de concluir que hay fuga.

## 11. Criterios de aceptación

| Código | Criterio | Evidencia requerida |
|---|---|---|
| `CA01` | Se identifica cada worker y su pool | PID, identidad de pool y configuración efectiva |
| `CA02` | Las operaciones devuelven conexiones al pool | `busy=0` tras finalizar las peticiones, sin operaciones pendientes |
| `CA03` | Se cumple el máximo configurado por pool | `opened <= pool_max` por worker en régimen normal |
| `CA04` | La inactividad libera conexiones físicas cuando el entorno lo permite | Series temporales del pool y sesiones Oracle, con condiciones documentadas |
| `CA05` | Tras quedar en `opened=0`, el pool puede reutilizarse | Nueva operación HTTP/Oracle correcta sin reinicio |
| `CA06` | CRUD y procedimiento mantienen integridad transaccional | Estado antes/después en Oracle y errores controlados |
| `CA07` | Concurrencia no produce crecimiento permanente de sesiones | Comparación de línea base, carga y reposo |
| `CA08` | Apagado de workers libera los pools | Logs de cierre y descenso posterior de sesiones Oracle |
| `CA09` | Monitorear no altera el pool medido | Monitor con identidad/conexión propias |
| `CA10` | Las conclusiones son reproducibles | Configuración, versiones, fechas, CSV/JSON y logs conservados |

Se emitirá **APTO**, **NO APTO** o **INCONCLUSO** por criterio y por configuración probada. Un CRUD correcto no equivale a certificar el ciclo de vida de conexiones.

## 12. Secuencia de construcción, archivo por archivo

No se implementarán todos los componentes a la vez. Cada etapa termina con una revisión antes de pasar a la siguiente.

| Fase | Entregables | Condición para avanzar |
|---|---|---|
| **F0. Especificación** | `README.md` aprobado | Alcance, archivos y contratos cerrados |
| **F1. Oracle** | `config/sql/01_instalacion.sql`, `02_consultas_monitor.sql`, `03_desinstalacion.sql` | DDL, procedimiento y limpieza validados en DBeaver |
| **F2. Configuración** | `config/config.json`, credenciales, `utils/logger.py`, `requirements.txt`, `scripts/validar_conexiones.py`, `.gitignore` | Dependencias identificadas y dos conexiones Oracle verificadas desde el entorno real |
| **F3. Cliente y servicio** | Copia `oracle_client.py`, `config_loader.py`, `test_service.py` | CRUD y SP funcionales desde Python |
| **F4. API** | `main.py`, routers y `diagnostics_service.py` | Endpoints y ciclo de vida revisados |
| **F5. Servidores** | `gunicorn.conf.py`, scripts de arranque | Comportamiento reproducible con 1 y varios workers |
| **F6. Monitores** | Módulos `monitoring/` y `run_monitor.py` | Medidas atribuibles a cada componente |
| **F7. Ensayos** | `tests/`, informes y logs | Matriz de aceptación con evidencias |

**Regla de mantenimiento:** si durante la implementación cambian nombres de archivos, contratos de API, estructura Oracle o criterios de aceptación, primero se actualizará este README y después el código.

## 13. Estado de avance

- [x] `README.md` revisado y aprobado.
- [x] Objetos Oracle instalados y comprobados.
- [x] Configuración de laboratorio y conectividad de las dos cuentas Oracle comprobadas desde el entorno real.
- [x] Copia base de `OracleClient` preservada.
- [ ] CRUD y procedimiento disponibles en FastAPI.
- [ ] Diagnósticos de workers y pools disponibles.
- [ ] Arranques Uvicorn/Gunicorn comprobados.
- [ ] Monitor independiente validado.
- [ ] Ensayos `T01`–`T10` ejecutados.
- [ ] Informe final de aceptación emitido.

## 14. Criterio de cierre del proyecto

El proyecto finalizará cuando exista evidencia repetible de creación, devolución, liberación, recuperación y cierre de conexiones Oracle en las configuraciones seleccionadas, con resultados de concurrencia y multiworker, **sin trasladar conclusiones del laboratorio a `Backend_Oracle` hasta comprobar que sus condiciones de ejecución son equivalentes**.


## 15. Implementacion F3/F4 - API y servicios (30/10/2026)

Se han implementado los cinco archivos ya previstos: `main.py`,
`module/test_service.py`, `module/diagnostics_service.py`,
`router/test_api.py` y `router/diagnostics_api.py`. La estructura de
carpetas, los objetos F1 y `module/oracle_client.py` 1.6.2 NO se alteran.

### 15.1. Contrato HTTP detallado

Todas las rutas parten de `/api/v1/lab`.

- `POST /registros`: cuerpo JSON obligatorio `run_id`, `codigo`; opcionales
  `descripcion`, `valor` (por defecto 0) y `estado` (por defecto ACTIVO).
  Responde `201` con `success` y el registro creado.
- `GET /registros?run_id=...&limit=100&offset=0`: lista una campana con
  paginacion (maximo 500 por pagina).
- `GET /registros/{id}?run_id=...`: lectura de una sola fila.
- `PUT /registros/{id}`: cuerpo completo con `run_id`, `codigo`,
  `descripcion`, `valor`, `estado`. Devuelve la fila actualizada.
- `DELETE /registros/{id}?run_id=...`: borrado fisico de la fila y campana.
- `POST /registros/{id}/procedimiento`: cuerpo JSON con `run_id` y
  `nuevo_valor`; invoca `SP_LAB_POOL_OPERACION` con tres IN y dos OUT.
- `GET /health`: no utiliza Oracle y no aumenta `pool.opened`.
- `GET /diagnostics/worker`: identifica PID, PPID, driver y pool del worker.
- `GET /diagnostics/pool`: instantanea de `opened`, `busy`, `min`, `max`,
  `increment`, `timeout`; no utiliza `acquire()` ni crea conexiones.

Las operaciones son SINCRONAS y se ejecutan en el threadpool de FastAPI;
no bloquean directamente el event loop con consultas Oracle sincronas.
Los identificadores `run_id` son obligatorios en consultas y modificaciones,
y el esquema propietario `AHJPS_M` se establece como constante en
`module/test_service.py` para evitar concatenacion de datos del usuario.
La precision de `VALOR` se limita al `NUMBER(18,4)` de la tabla.

El servicio utiliza `execute_dml()`, `execute_query_json()` y
`call_procedure_out_scalars()` de OracleClient 1.6.2. El commit permanece
controlado por esos metodos originales. En CREATE y UPDATE se realiza un
SELECT adicional tras el commit, por lo que esa lectura NO forma parte de
la misma transaccion que la escritura.

### 15.2. Sesiones asociadas a un worker concreto

Cada worker asigna `CLIENT_IDENTIFIER=LAB_POOL_API` y `CLIENT_INFO` con
`FastAPI_Oracle_Lab/PID=<PID>`. Esto permite correlacionar `V$SESSION` con
el PID y el identificador del pool informado en `/diagnostics/worker`.
El monitor externo permanece separado y usa `LAB_POOL_MONITOR`.

La identificacion del PID se fija en el contexto de sesion al adquirir
una conexion mediante `_set_session_context()` del OracleClient original.
Una consulta del monitor puede recuperar `CLIENT_INFO` de `V$SESSION` sin
que sea necesario cambiar los objetos SQL ya instalados.

### 15.3. Ciclo de vida y limites de esta fase

- FastAPI crea el pool **durante `lifespan` dentro del worker**, no durante
  la importacion de `main.py`; Gunicorn no debe usar `--preload` para
  crear pools en el proceso master.
- El pool se cierra una sola vez durante el apagado ordenado del worker.
- `oracle_client.py` 1.6.2 permanece byte a byte igual que el original.
  Las opciones `timeout`, `increment`, `getmode`, `wait_timeout` del JSON
  siguen fijadas dentro de esa biblioteca: el arranque advierte si hay
  discrepancias, y los diagnosticos muestran los valores realmente activos.
- `/diagnostics/worker` y `/diagnostics/pool` solo permiten clientes desde
  loopback (`127.0.0.1` o `::1`). No exponer la API CRUD a Internet ni a
  una red no controlada: esta fase NO incorpora autenticacion.
- Un GET de diagnosticos refleja el worker que responde; con varios
  workers no representa un agregado de los pools existentes.
- En este laboratorio no se aplica un mecanismo nuevo de reintentos:
  permanecen los reintentos que ya incorpora OracleClient 1.6.2.

### 15.4. Primera ejecucion local y validacion

Desde la raiz del proyecto con `LAB_API` previamente validado en F2:

```bash
source .venv/bin/activate
python -m uvicorn main:app --host 127.0.0.1 --port 8010 --workers 1
```

Consultar `http://127.0.0.1:8010/docs` para operar la API y
`http://127.0.0.1:8010/api/v1/lab/diagnostics/pool` para leer el pool.
Para cada campaña elegir un `run_id` nuevo y realizar CRUD y SP solo sobre
registros de esa campana. Los scripts de arranque parametrizados y las
pruebas automaticas de carga se implementaran en F5/F7.

Validacion disponible al entregar F3/F4: compilacion Python, ensayos HTTP
simulados de CRUD/PUT/DELETE/SP/errores y ensayo simulado de `lifespan`
(creacion y cierre del pool). **Pendiente**: ejecutar CRUD/SP contra
Oracle 19c real desde el entorno del usuario y comprobar sesiones.

Las versiones comprobadas por el usuario son: laboratorio Python 3.14.8,
python-oracledb 26.1.0 Thin; backend de referencia Python 3.14.4,
python-oracledb 1.2.1 Thin. No extrapolar conclusiones entre versiones.

## 16. F6 monitores y F7/T06 — concurrencia real (30/10/2026)

Se incorpora el escenario `T06` sin modificar `module/oracle_client.py` ni los
objetos SQL de F1. Se mantiene `gunicorn.conf.py` y la propiedad de un pool
por worker. Se documenta en `docs/F6_T06_guia.md` el procedimiento y el
criterio de interpretación de resultados.

**Contrato de la nueva API:**

- `POST /api/v1/lab/concurrency/hold`, **solo desde loopback**.
- JSON: `{"run_id":"LAB_T06_20261030_A","segundos":3}`; `run_id` solo admite
  `[A-Za-z0-9_-]` y máximo 64 caracteres; `segundos` 0,1..5,0.
- El endpoint es `def` síncrono y se ejecuta desde el threadpool FastAPI.
- El servicio ejecuta `BEGIN DBMS_SESSION.SLEEP(:segundos); END;` mediante
  `OracleClient.execute_dml()` original, por lo que la conexion queda adquirida
  durante la espera del procedimiento. No modifica registros Oracle.
- Respuesta HTTP 200 `success=true`, `pid`, `run_id`, `segundos_solicitados`,
  `duracion_total_ms`, `espera_pool_ms`, `duracion_operacion_oracle_ms`.
- Si falta permiso para DBMS_SESSION, el preflight fallara y se documentara el
  error, sin modificar permisos ni libreria base.

**Monitores F6:** `monitoring/oracle_monitor.py`, `process_monitor.py`,
`metrics_collector.py` y `scripts/run_monitor.py`. El monitor usa `LAB_MONITOR`
y una instancia/identidad `LAB_POOL_MONITOR` independientes. Sus consultas
sobre `V$SESSION` filtran `LAB_POOL_API`, sin contar el monitor.
Las mediciones HTTP de `/diagnostics/pool` son parciales por naturaleza:
puede repetirse PID durante la muestra; una solicitud no observa todos los
pools. Los registros CSV conservan muestras y errores sin interpretarlos como
cero sesiones.

**Generador de carga F7/T06:** `tests/test_concurrency.py`, sin dependencia
externa adicional. Utiliza hasta 16 solicitudes concurrentes, cada una con
5 segundos de espera Oracle como maximo; conserva solicitudes, errores,
latencias y PID en CSV/JSON. Empezar con 2 workers y concurrencia 4 antes de
subir de forma controlada; el limite teorico 8*5=40 NO implica 40 conexiones
abiertas. No se considera APTO el ensayo hasta ejecutarlo realmente en Oracle
19c, comparar `busy`/sesiones activas durante carga y analizar el reposo.

**Situacion a la entrega del codigo:** sintaxis y contratos revisados en local;
la ejecucion real de T06 frente a la instancia Oracle del usuario queda pendiente.

**Analisis final F7/T06:** `scripts/analyze_t06.py` produce informes en
`reports/resultados/<run_id>/report.md` y `report.json` a partir de
los CSV/JSON, sin acceder a Oracle; el estado automatico es preliminar.
