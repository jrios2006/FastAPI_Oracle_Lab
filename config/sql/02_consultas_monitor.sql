-- ============================================================================
-- FastAPI_Oracle_Lab - F1 / Oracle 19c
-- Archivo : config/sql/02_consultas_monitor.sql
-- Objetivo: consultas de solo lectura para monitorizar los pools del lab.
--
-- Ejecutar manualmente en DBeaver con usuario de monitorizacion, separado
-- de la cuenta que usa FastAPI. Requiere SELECT sobre V_$SESSION y
-- V_$RESOURCE_LIMIT (u otros privilegios de lectura equivalentes).
-- No utilizar el pool medido para ejecutar estas consultas.
--
-- Convencion de identidad prevista para la fase de implementacion Python:
--   CLIENT_IDENTIFIER = 'LAB_POOL_API'
--   o CLIENT_IDENTIFIER que comience exactamente por 'LAB_POOL_API:'
--   (se podra anadir el PID a continuacion de los dos puntos).
-- El monitor utilizara otra identidad: 'LAB_POOL_MONITOR'.
-- Esta convencion NO reutiliza 'THW_PHOTOS' del backend principal.
--
-- ATENCION: la etiqueta CLIENT_IDENTIFIER se establece al adquirir una
-- conexion y puede conservarse en la sesion despues de devolverla al pool.
-- STATUS = 'INACTIVE' NO demuestra que la conexion este libre dentro del pool.
-- Para certificarlo se cotejara con pool.opened y pool.busy por worker.
--
-- Medir repetidamente antes, durante y despues de las pruebas (T01-T10).
-- Oracle V$SESSION no conserva historico; el muestreo temporal se implementara
-- en monitoring/oracle_monitor.py en la fase F6.
-- ============================================================================

-- M01. Conteo instantaneo de sesiones identificadas como LAB_POOL_API.
-- Devuelve una fila, incluso si no hay sesiones; NVL evita sumas NULL.
SELECT
    SYSTIMESTAMP AS FECHA_MEDICION,
    COUNT(*) AS TOTAL_SESIONES,
    NVL(SUM(CASE WHEN S.STATUS = 'ACTIVE' THEN 1 ELSE 0 END), 0) AS ACTIVAS,
    NVL(SUM(CASE WHEN S.STATUS = 'INACTIVE' THEN 1 ELSE 0 END), 0) AS INACTIVAS,
    MAX(CASE WHEN S.STATUS = 'INACTIVE' THEN S.LAST_CALL_ET END)
        AS MAX_SEGUNDOS_INACTIVA
FROM V$SESSION S
WHERE S.TYPE = 'USER'
  AND (
      S.CLIENT_IDENTIFIER = 'LAB_POOL_API'
      OR SUBSTR(S.CLIENT_IDENTIFIER, 1, 13) = 'LAB_POOL_API:'
  );

-- M02. Desglose completo para atribuir sesiones a procesos y workers.
-- PROCESS corresponde al proceso CLIENTE comunicado a Oracle; SPID (V$PROCESS)
-- seria un proceso del servidor Oracle, no el PID Gunicorn.
SELECT
    SYSTIMESTAMP AS FECHA_MEDICION,
    S.SID,
    S.SERIAL#,
    S.USERNAME,
    S.MACHINE,
    S.PROGRAM,
    S.MODULE,
    S.CLIENT_IDENTIFIER,
    S.PROCESS AS PROCESO_CLIENTE,
    S.STATUS,
    S.LAST_CALL_ET AS SEGUNDOS_EN_ESTADO,
    S.LOGON_TIME
FROM V$SESSION S
WHERE S.TYPE = 'USER'
  AND (
      S.CLIENT_IDENTIFIER = 'LAB_POOL_API'
      OR SUBSTR(S.CLIENT_IDENTIFIER, 1, 13) = 'LAB_POOL_API:'
  )
ORDER BY S.MACHINE, S.CLIENT_IDENTIFIER, S.LOGON_TIME, S.SID;

-- M03. Sesiones por identidad de aplicacion y proceso cliente.
-- Diferencia grupos del pool incluso si Oracle los muestra INACTIVE.
SELECT
    S.MACHINE,
    S.CLIENT_IDENTIFIER,
    S.PROCESS AS PROCESO_CLIENTE,
    S.STATUS,
    COUNT(*) AS TOTAL_SESIONES,
    MIN(S.LAST_CALL_ET) AS MIN_SEGUNDOS_EN_ESTADO,
    MAX(S.LAST_CALL_ET) AS MAX_SEGUNDOS_EN_ESTADO,
    MIN(S.LOGON_TIME) AS PRIMERA_CONEXION,
    MAX(S.LOGON_TIME) AS ULTIMA_CONEXION
FROM V$SESSION S
WHERE S.TYPE = 'USER'
  AND (
      S.CLIENT_IDENTIFIER = 'LAB_POOL_API'
      OR SUBSTR(S.CLIENT_IDENTIFIER, 1, 13) = 'LAB_POOL_API:'
  )
GROUP BY S.MACHINE, S.CLIENT_IDENTIFIER, S.PROCESS, S.STATUS
ORDER BY S.MACHINE, S.CLIENT_IDENTIFIER, S.PROCESS, S.STATUS;

-- M04. Limites globales de Oracle. Son limites de la instancia, NO de un pool.
SELECT
    SYSTIMESTAMP AS FECHA_MEDICION,
    RESOURCE_NAME,
    CURRENT_UTILIZATION,
    MAX_UTILIZATION,
    LIMIT_VALUE
FROM V$RESOURCE_LIMIT
WHERE RESOURCE_NAME IN ('processes', 'sessions')
ORDER BY RESOURCE_NAME;

-- M05. Identificar sesiones del monitor (separadas del servicio medido).
-- El monitor puede aparecer ACTIVE mientras ejecuta esta misma consulta.
SELECT
    SYSTIMESTAMP AS FECHA_MEDICION,
    S.CLIENT_IDENTIFIER,
    S.MACHINE,
    S.STATUS,
    COUNT(*) AS TOTAL_SESIONES
FROM V$SESSION S
WHERE S.TYPE = 'USER'
  AND S.CLIENT_IDENTIFIER = 'LAB_POOL_MONITOR'
GROUP BY S.CLIENT_IDENTIFIER, S.MACHINE, S.STATUS
ORDER BY S.MACHINE, S.STATUS;

-- M06. Verificar presencia de objetos y volumen de filas por RUN_ID.
-- Requiere SELECT sobre LAB_POOL_REGISTROS, y no modifica datos.
SELECT
    RUN_ID,
    COUNT(*) AS TOTAL_REGISTROS,
    MIN(FCREACION) AS PRIMERA_ALTA,
    MAX(FCREACION) AS ULTIMA_ALTA,
    MAX(FMODIFICACION) AS ULTIMA_MODIFICACION
FROM LAB_POOL_REGISTROS
GROUP BY RUN_ID
ORDER BY RUN_ID;

-- Consideraciones de interpretacion:
-- - 0 sesiones despues del reposo + API recuperable = evidencia positiva.
-- - 40 sesiones INACTIVE no implica por si solo fuga: verificar busy y workers.
-- - Si se recrea el pool o se reinician workers, registrar PID/fecha del cambio.
-- - Para aislar un unico laboratorio en un Oracle compartido, configurar una
--   identidad exclusiva y, preferentemente, un usuario Oracle de laboratorio.
