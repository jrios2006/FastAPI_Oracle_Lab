-- ============================================================================
-- FastAPI_Oracle_Lab - F1 / Oracle 19c
-- Archivo : config/sql/01_instalacion.sql
-- Objetivo: crear SOLO los dos objetos de laboratorio indicados en README.md.
--
-- Objetos:
--   1. LAB_POOL_REGISTROS       (tabla de pruebas CRUD)
--   2. SP_LAB_POOL_OPERACION   (procedimiento de actualizacion y pruebas)
--
-- EJECUCION MANUAL en DBeaver, usando "Ejecutar script SQL" para procesar
-- correctamente el bloque PL/SQL y su delimitador '/' en linea propia.
-- Ejecutar conectado como el propietario DEL ESQUEMA DE LABORATORIO.
-- No ejecutar en el esquema de produccion ni con CURRENT_SCHEMA modificado.
-- No se crean usuarios, permisos, sesiones, jobs ni datos de prueba.
--
-- Seguridad: si existen objetos con estos nombres, la instalacion se detiene.
-- Nunca se borran ni reemplazan automaticamente objetos previos.
-- ============================================================================

-- 0. Verificaciones de seguridad antes de modificar el esquema.
DECLARE
    v_existentes PLS_INTEGER;
BEGIN
    IF SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') <>
       SYS_CONTEXT('USERENV', 'SESSION_USER') THEN
        RAISE_APPLICATION_ERROR(
            -20090,
            'Instalacion bloqueada: CURRENT_SCHEMA distinto de SESSION_USER'
        );
    END IF;

    SELECT COUNT(*)
      INTO v_existentes
      FROM USER_OBJECTS
     WHERE OBJECT_NAME IN ('LAB_POOL_REGISTROS', 'SP_LAB_POOL_OPERACION');

    IF v_existentes > 0 THEN
        RAISE_APPLICATION_ERROR(
            -20091,
            'Ya existen objetos de laboratorio. Revisar antes de instalar.'
        );
    END IF;
END;
/

-- 1. Tabla de laboratorio.
-- La PK de identidad no requiere secuencia creada manualmente.
-- La restriccion UNIQUE (RUN_ID, CODIGO) crea su propio indice, util tambien
-- para consultas filtradas por RUN_ID. No creamos un indice redundante.
-- Las marcas de fecha conservan el huso horario para cotejar con logs UTC.
CREATE TABLE LAB_POOL_REGISTROS (
    ID              NUMBER GENERATED ALWAYS AS IDENTITY,
    RUN_ID          VARCHAR2(64 CHAR)                     NOT NULL,
    CODIGO          VARCHAR2(80 CHAR)                     NOT NULL,
    DESCRIPCION     VARCHAR2(500 CHAR),
    VALOR           NUMBER(18, 4) DEFAULT 0               NOT NULL,
    ESTADO          VARCHAR2(16 CHAR) DEFAULT 'ACTIVO'     NOT NULL,
    FCREACION       TIMESTAMP(6) WITH TIME ZONE
                    DEFAULT SYSTIMESTAMP                  NOT NULL,
    FMODIFICACION   TIMESTAMP(6) WITH TIME ZONE,

    CONSTRAINT PK_LAB_POOL_REGISTROS PRIMARY KEY (ID),
    CONSTRAINT UK_LAB_POOL_REG_RUN_COD UNIQUE (RUN_ID, CODIGO),
    CONSTRAINT CK_LAB_POOL_REG_ESTADO CHECK (ESTADO IN ('ACTIVO', 'INACTIVO'))
);

COMMENT ON TABLE LAB_POOL_REGISTROS IS
    'Datos sinteticos del laboratorio FastAPI/Oracle: CRUD y concurrencia por RUN_ID';
COMMENT ON COLUMN LAB_POOL_REGISTROS.RUN_ID IS
    'Identificador de la campana de pruebas; aisla consultas, UPDATE y DELETE';
COMMENT ON COLUMN LAB_POOL_REGISTROS.CODIGO IS
    'Clave funcional unica dentro del RUN_ID';
COMMENT ON COLUMN LAB_POOL_REGISTROS.VALOR IS
    'Valor numerico modificable por CRUD y SP_LAB_POOL_OPERACION';

-- 2. Procedimiento de laboratorio.
-- Firma posicional para la futura llamada desde python-oracledb:
--   (p_id IN, p_nuevo_valor IN, p_run_id IN,
--    p_resultado OUT VARCHAR2, p_filas_afectadas OUT NUMBER)
--
-- Errores funcionales:
--   ORA-20010 ID nulo, negativo, cero o no entero
--   ORA-20011 RUN_ID vacio
--   ORA-20012 Valor numerico nulo
--   ORA-20013 Registro inexistente
--   ORA-20014 Registro perteneciente a otra campana
--   ORA-20015 No se ha actualizado exactamente una fila
--
-- El SELECT FOR UPDATE asegura que las comprobaciones y el UPDATE ocurren
-- bajo bloqueo de la misma fila para los ensayos transaccionales.
-- IMPORTANTE: no incluye COMMIT ni ROLLBACK. El llamador es responsable.
CREATE PROCEDURE SP_LAB_POOL_OPERACION (
    p_id                IN  LAB_POOL_REGISTROS.ID%TYPE,
    p_nuevo_valor       IN  LAB_POOL_REGISTROS.VALOR%TYPE,
    p_run_id            IN  LAB_POOL_REGISTROS.RUN_ID%TYPE,
    p_resultado         OUT VARCHAR2,
    p_filas_afectadas   OUT NUMBER
)
AS
    v_run_id LAB_POOL_REGISTROS.RUN_ID%TYPE;
BEGIN
    p_resultado       := NULL;
    p_filas_afectadas := 0;

    IF p_id IS NULL OR p_id <= 0 OR p_id <> TRUNC(p_id) THEN
        RAISE_APPLICATION_ERROR(-20010, 'ID de registro no valido');
    END IF;

    IF TRIM(p_run_id) IS NULL THEN
        RAISE_APPLICATION_ERROR(-20011, 'RUN_ID obligatorio');
    END IF;

    IF p_nuevo_valor IS NULL THEN
        RAISE_APPLICATION_ERROR(-20012, 'Nuevo valor obligatorio');
    END IF;

    BEGIN
        SELECT RUN_ID
          INTO v_run_id
          FROM LAB_POOL_REGISTROS
         WHERE ID = p_id
           FOR UPDATE;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RAISE_APPLICATION_ERROR(-20013, 'Registro no encontrado');
    END;

    IF v_run_id <> p_run_id THEN
        RAISE_APPLICATION_ERROR(-20014, 'Registro de otro RUN_ID');
    END IF;

    UPDATE LAB_POOL_REGISTROS
       SET VALOR         = p_nuevo_valor,
           FMODIFICACION = SYSTIMESTAMP
     WHERE ID = p_id
       AND RUN_ID = p_run_id;

    p_filas_afectadas := SQL%ROWCOUNT;

    IF p_filas_afectadas <> 1 THEN
        RAISE_APPLICATION_ERROR(-20015, 'Numero inesperado de filas actualizadas');
    END IF;

    p_resultado := 'OK';
END SP_LAB_POOL_OPERACION;
/

-- 3. Comprobaciones de objetos instalados y estado de compilacion.
-- Esperado: TABLE VALID y PROCEDURE VALID; dos filas.
SELECT OBJECT_NAME, OBJECT_TYPE, STATUS
  FROM USER_OBJECTS
 WHERE OBJECT_NAME IN ('LAB_POOL_REGISTROS', 'SP_LAB_POOL_OPERACION')
 ORDER BY OBJECT_TYPE, OBJECT_NAME;

-- Esperado: sin filas. Si devuelve errores, revisar antes de comenzar pruebas.
SELECT NAME, TYPE, LINE, POSITION, TEXT
  FROM USER_ERRORS
 WHERE NAME = 'SP_LAB_POOL_OPERACION'
 ORDER BY SEQUENCE;
