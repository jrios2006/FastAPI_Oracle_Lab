-- ============================================================================
-- FastAPI_Oracle_Lab - F1 / Oracle 19c
-- Archivo : config/sql/03_desinstalacion.sql
-- Objetivo: eliminar EXCLUSIVAMENTE los objetos del laboratorio.
--
-- ADVERTENCIA: destruye los registros de pruebas existentes en
-- LAB_POOL_REGISTROS. Se ejecuta SOLO de forma manual en DBeaver.
-- Detener primero la API y los monitores que dependen de estos objetos.
-- Ejecutar conectado como propietario del esquema de laboratorio.
-- No realizar ALTER SESSION SET CURRENT_SCHEMA hacia otro propietario.
--
-- Es seguro repetir el script: si alguno de los dos objetos no existe,
-- lo omite. No utiliza patrones de nombres ni elimina objetos ajenos.
-- No borra usuarios, permisos globales, logs, jobs ni otros esquemas.
-- ============================================================================

DECLARE
    v_existe PLS_INTEGER;
BEGIN
    IF SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') <>
       SYS_CONTEXT('USERENV', 'SESSION_USER') THEN
        RAISE_APPLICATION_ERROR(
            -20090,
            'Desinstalacion bloqueada: CURRENT_SCHEMA distinto de SESSION_USER'
        );
    END IF;

    -- Primero se elimina el procedimiento dependiente de la tabla.
    SELECT COUNT(*)
      INTO v_existe
      FROM USER_OBJECTS
     WHERE OBJECT_NAME = 'SP_LAB_POOL_OPERACION'
       AND OBJECT_TYPE = 'PROCEDURE';

    IF v_existe = 1 THEN
        EXECUTE IMMEDIATE 'DROP PROCEDURE SP_LAB_POOL_OPERACION';
        DBMS_OUTPUT.PUT_LINE('Eliminado: SP_LAB_POOL_OPERACION');
    ELSE
        DBMS_OUTPUT.PUT_LINE('No existe: SP_LAB_POOL_OPERACION');
    END IF;

    -- Solo se purga la tabla concreta del proyecto (sin CASCADE CONSTRAINTS).
    SELECT COUNT(*)
      INTO v_existe
      FROM USER_OBJECTS
     WHERE OBJECT_NAME = 'LAB_POOL_REGISTROS'
       AND OBJECT_TYPE = 'TABLE';

    IF v_existe = 1 THEN
        EXECUTE IMMEDIATE 'DROP TABLE LAB_POOL_REGISTROS PURGE';
        DBMS_OUTPUT.PUT_LINE('Eliminada: LAB_POOL_REGISTROS');
    ELSE
        DBMS_OUTPUT.PUT_LINE('No existe: LAB_POOL_REGISTROS');
    END IF;
END;
/

-- Verificacion de ausencia. Esperado: ninguna fila.
SELECT OBJECT_NAME, OBJECT_TYPE, STATUS
  FROM USER_OBJECTS
 WHERE OBJECT_NAME IN ('LAB_POOL_REGISTROS', 'SP_LAB_POOL_OPERACION')
 ORDER BY OBJECT_TYPE, OBJECT_NAME;
