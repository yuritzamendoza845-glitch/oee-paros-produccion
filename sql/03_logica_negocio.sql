-- =====================================================================================
-- 03_logica_negocio.sql | Reglas de integridad, triggers, auditoría y procedimientos del ETL
-- Requiere 01_ddl.sql y 02_seed_catalogos.sql.   PostgreSQL 14+ (CREATE PROCEDURE).
-- =====================================================================================

-- ------------------------------------------------------------------ AUDITORÍA GENÉRICA
CREATE OR REPLACE FUNCTION audit.fn_log() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_pk text;
BEGIN
    v_pk := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ->> TG_ARGV[0]
                 ELSE to_jsonb(NEW) ->> TG_ARGV[0] END;
    INSERT INTO audit.log_cambios (tabla, pk, operacion, antes, despues)
    VALUES (TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME, v_pk, TG_OP,
            CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END,
            CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END);
    RETURN NULL;
END $$;

-- Hechos: solo se auditan cambios de negocio (UPDATE OF ... / DELETE). Los INSERT masivos del ETL
-- ya quedan trazados por etl.lotes (lote_id) y los recálculos internos de totales no disparan el trigger.
DROP TRIGGER IF EXISTS trg_audit_registros ON oee.registros_produccion;
CREATE TRIGGER trg_audit_registros
    AFTER UPDATE OF fecha, maquina_id, turno_id, operario_id, referencia_id, pacas_producidas,
                    pacas_no_conformes, horas_programadas, horas_no_programadas, tipo_registro
          OR DELETE
    ON oee.registros_produccion
    FOR EACH ROW EXECUTE FUNCTION audit.fn_log('registro_id');

DROP TRIGGER IF EXISTS trg_audit_detalle ON oee.detalle_paros_produccion;
CREATE TRIGGER trg_audit_detalle
    AFTER UPDATE OF motivo_id, subcodigo_id, minutos, inicio, fin OR DELETE
    ON oee.detalle_paros_produccion
    FOR EACH ROW EXECUTE FUNCTION audit.fn_log('detalle_id');

-- Maestros críticos: auditoría completa (cambiar es_planificado altera todo el OEE histórico)
DROP TRIGGER IF EXISTS trg_audit_motivo ON oee.dim_motivo_paro;
CREATE TRIGGER trg_audit_motivo AFTER INSERT OR UPDATE OR DELETE ON oee.dim_motivo_paro
    FOR EACH ROW EXECUTE FUNCTION audit.fn_log('motivo_id');
DROP TRIGGER IF EXISTS trg_audit_meta ON oee.meta_produccion;
CREATE TRIGGER trg_audit_meta AFTER INSERT OR UPDATE OR DELETE ON oee.meta_produccion
    FOR EACH ROW EXECUTE FUNCTION audit.fn_log('maquina_id');

-- ------------------------------------------------------------------ REGLAS: REGISTRO
CREATE OR REPLACE FUNCTION oee.fn_registro_validar() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.pacas_no_conformes > COALESCE(NEW.pacas_producidas, 0) THEN
        RAISE EXCEPTION 'Pacas no conformes (%) no puede superar las producidas (%)',
            NEW.pacas_no_conformes, COALESCE(NEW.pacas_producidas, 0)
            USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        NEW.actualizado_en := now();
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_registro_validar ON oee.registros_produccion;
CREATE TRIGGER trg_registro_validar BEFORE INSERT OR UPDATE ON oee.registros_produccion
    FOR EACH ROW EXECUTE FUNCTION oee.fn_registro_validar();

-- ------------------------------------------------------------------ REGLAS: DETALLE DE PAROS
-- (a) BEFORE: hereda la máquina del registro y, si hay marcas de tiempo, impone minutos = fin - inicio.
--     El no solapamiento temporal por máquina lo garantiza la restricción EXCLUDE del DDL (SQLSTATE 23P01).
CREATE OR REPLACE FUNCTION oee.fn_detalle_before() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    SELECT maquina_id INTO NEW.maquina_id FROM oee.registros_produccion WHERE registro_id = NEW.registro_id;
    IF NEW.maquina_id IS NULL THEN
        RAISE EXCEPTION 'Registro % inexistente', NEW.registro_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NEW.inicio IS NOT NULL AND NEW.fin IS NOT NULL THEN
        IF NEW.fin <= NEW.inicio THEN
            RAISE EXCEPTION 'El paro termina (%) antes de empezar (%)', NEW.fin, NEW.inicio
                USING ERRCODE = 'check_violation';
        END IF;
        NEW.minutos := round(extract(epoch FROM (NEW.fin - NEW.inicio)) / 60.0, 2);
    END IF;
    IF NEW.subcodigo_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM oee.dim_subcodigo_paro s WHERE s.subcodigo_id = NEW.subcodigo_id AND s.motivo_id = NEW.motivo_id) THEN
        RAISE EXCEPTION 'El subcódigo % no pertenece al código de paro %', NEW.subcodigo_id, NEW.motivo_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_detalle_before ON oee.detalle_paros_produccion;
CREATE TRIGGER trg_detalle_before BEFORE INSERT OR UPDATE ON oee.detalle_paros_produccion
    FOR EACH ROW EXECUTE FUNCTION oee.fn_detalle_before();

-- (b) AFTER: recalcula los totales del registro y marca 'REVISAR' si los paros exceden el tiempo
--     del turno (+5 min de tolerancia). No bloquea la carga histórica: la inconsistencia queda visible.
CREATE OR REPLACE FUNCTION oee.fn_detalle_after() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_id bigint := CASE WHEN TG_OP = 'DELETE' THEN OLD.registro_id ELSE NEW.registro_id END;
BEGIN
    UPDATE oee.registros_produccion r
       SET paro_planificado_min    = COALESCE(x.planificado, 0),
           paro_no_planificado_min = COALESCE(x.no_planificado, 0),
           calidad_dato = CASE
               WHEN r.calidad_dato = 'OK' AND r.horas_programadas > 0
                    AND COALESCE(x.planificado, 0) + COALESCE(x.no_planificado, 0) > r.horas_programadas * 60 + 5
               THEN 'REVISAR' ELSE r.calidad_dato END
      FROM (SELECT sum(d.minutos) FILTER (WHERE m.es_planificado)     AS planificado,
                   sum(d.minutos) FILTER (WHERE NOT m.es_planificado) AS no_planificado
              FROM oee.detalle_paros_produccion d
              JOIN oee.dim_motivo_paro m USING (motivo_id)
             WHERE d.registro_id = v_id) x
     WHERE r.registro_id = v_id;
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS trg_detalle_after ON oee.detalle_paros_produccion;
CREATE TRIGGER trg_detalle_after AFTER INSERT OR UPDATE OF minutos, motivo_id OR DELETE
    ON oee.detalle_paros_produccion
    FOR EACH ROW EXECUTE FUNCTION oee.fn_detalle_after();

-- ------------------------------------------------------------------ API PARA HMI / CAPTURA DIRECTA
-- Registra un paro con marcas de tiempo y devuelve el id; ante solapamiento da un mensaje claro.
CREATE OR REPLACE FUNCTION oee.fn_registrar_paro(
    p_registro bigint, p_motivo smallint, p_inicio timestamptz, p_fin timestamptz,
    p_subcodigo text DEFAULT NULL, p_area text DEFAULT NULL, p_personal text DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE
    v_sub integer; v_id bigint; v_maq smallint; v_choque record;
BEGIN
    SELECT maquina_id INTO v_maq FROM oee.registros_produccion WHERE registro_id = p_registro;
    IF v_maq IS NULL THEN RAISE EXCEPTION 'Registro % no existe', p_registro; END IF;
    SELECT d.detalle_id, d.inicio, d.fin INTO v_choque
      FROM oee.detalle_paros_produccion d
     WHERE d.maquina_id = v_maq AND d.inicio IS NOT NULL
       AND tstzrange(d.inicio, d.fin, '[)') && tstzrange(p_inicio, p_fin, '[)') LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'Solapamiento con el paro % (% → %) en la misma máquina',
            v_choque.detalle_id, v_choque.inicio, v_choque.fin USING ERRCODE = 'exclusion_violation';
    END IF;
    IF p_subcodigo IS NOT NULL THEN
        SELECT subcodigo_id INTO v_sub FROM oee.dim_subcodigo_paro WHERE motivo_id = p_motivo AND clave = p_subcodigo;
        IF v_sub IS NULL THEN RAISE EXCEPTION 'Subcódigo % no existe para el código %', p_subcodigo, p_motivo; END IF;
    END IF;
    INSERT INTO oee.detalle_paros_produccion (registro_id, motivo_id, subcodigo_id, minutos, inicio, fin, area_involucrada, personal_involucrado)
    VALUES (p_registro, p_motivo, v_sub, 1, p_inicio, p_fin, p_area, p_personal)   -- minutos lo recalcula el trigger
    RETURNING detalle_id INTO v_id;
    RETURN v_id;
END $$;

-- ------------------------------------------------------------------ FUNCIONES DEL PIPELINE ETL
-- Devuelve NULL si el mismo archivo (SHA-256) ya fue cargado con éxito => ejecución idempotente.
CREATE OR REPLACE FUNCTION etl.fn_iniciar_lote(p_archivo text, p_sha text, p_filas integer) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE v_id bigint;
BEGIN
    IF EXISTS (SELECT 1 FROM etl.lotes WHERE sha256 = p_sha AND estado = 'OK') THEN
        RETURN NULL;
    END IF;
    INSERT INTO etl.lotes (archivo, sha256, filas_leidas) VALUES (p_archivo, p_sha, p_filas)
    RETURNING lote_id INTO v_id;
    RETURN v_id;
END $$;

CREATE OR REPLACE FUNCTION etl.fn_registrar_error(p_archivo text, p_mensaje text) RETURNS void
LANGUAGE sql AS $$
    INSERT INTO etl.lotes (archivo, estado, finalizado_en, mensaje) VALUES (p_archivo, 'ERROR', now(), p_mensaje);
$$;

-- Meta estimada: no pisa metas OFICIALES. referencia NULL => meta por defecto de la máquina (id 0).
CREATE OR REPLACE FUNCTION etl.fn_upsert_meta_estimada(p_maquina text, p_referencia text, p_meta numeric) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v_maq smallint; v_ref integer;
BEGIN
    SELECT maquina_id INTO v_maq FROM oee.dim_maquina WHERE nombre = p_maquina;
    IF p_referencia IS NULL THEN v_ref := 0;
    ELSE SELECT referencia_id INTO v_ref FROM oee.dim_referencia WHERE nombre = p_referencia; END IF;
    IF v_maq IS NULL OR v_ref IS NULL OR p_meta IS NULL OR p_meta <= 0 THEN RETURN; END IF;
    INSERT INTO oee.meta_produccion (maquina_id, referencia_id, meta_pacas_hora, origen)
    VALUES (v_maq, v_ref, p_meta, 'ESTIMADA_P90')
    ON CONFLICT (maquina_id, referencia_id) DO UPDATE
        SET meta_pacas_hora = EXCLUDED.meta_pacas_hora, actualizado_en = now()
        WHERE oee.meta_produccion.origen <> 'OFICIAL';
END $$;

-- Promoción staging -> modelo (una sola transacción; el COMMIT lo hace quien llama).
CREATE OR REPLACE PROCEDURE etl.sp_promover_lote(p_lote bigint, p_reemplazar_desde date DEFAULT NULL)
LANGUAGE plpgsql AS $$
DECLARE
    v_ins integer := 0; v_upd integer := 0; v_del integer := 0; v_desconocidos integer;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM etl.lotes WHERE lote_id = p_lote AND estado = 'EN_CURSO') THEN
        RAISE EXCEPTION 'Lote % no existe o ya fue cerrado', p_lote;
    END IF;

    -- 1) Dimensiones dinámicas (operarios, referencias, tipos de paro de máquina)
    INSERT INTO oee.dim_operario (nombre)
    SELECT DISTINCT operario FROM stg.registros WHERE lote_id = p_lote AND operario IS NOT NULL
    ON CONFLICT (nombre) DO NOTHING;

    INSERT INTO oee.dim_referencia (nombre, marca, volumen_cc, num_colores)
    SELECT DISTINCT referencia,
           NULLIF(btrim(regexp_replace(referencia, '\s*\d+\s*cc.*$', '', 'i')), ''),
           substring(referencia FROM '(\d+)\s*[cC][cC]')::smallint,
           substring(referencia FROM '\((\d+)\s*col\)')::smallint
      FROM stg.registros WHERE lote_id = p_lote AND referencia IS NOT NULL
    ON CONFLICT (nombre) DO NOTHING;

    INSERT INTO oee.dim_tipo_paro_maquina (nombre, pierde_disponibilidad)
    SELECT tipo_paro_maquina, bool_or(COALESCE(pierde_disp_tpm, true))
      FROM stg.registros WHERE lote_id = p_lote AND tipo_paro_maquina IS NOT NULL GROUP BY 1
    ON CONFLICT (nombre) DO NOTHING;

    -- 2) Turnos o máquinas fuera de catálogo: se avisa (no se pierde el dato: queda como 'Sin dato')
    SELECT count(*) INTO v_desconocidos FROM stg.registros s
     WHERE s.lote_id = p_lote AND s.turno IS NOT NULL AND NOT EXISTS (SELECT 1 FROM oee.dim_turno t WHERE t.nombre = s.turno);
    IF v_desconocidos > 0 THEN
        INSERT INTO etl.rechazos (lote_id, fila_origen, regla, severidad, detalle)
        SELECT p_lote, s.fila_origen, 'R10_TURNO_NO_CATALOGADO', 'WARNING', 'turno=' || s.turno
          FROM stg.registros s
         WHERE s.lote_id = p_lote AND s.turno IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM oee.dim_turno t WHERE t.nombre = s.turno);
    END IF;

    -- 3) Ventana de re-sincronización: elimina lo que ya no existe en el archivo desde la fecha dada
    IF p_reemplazar_desde IS NOT NULL THEN
        DELETE FROM oee.registros_produccion r
         WHERE r.fecha >= p_reemplazar_desde
           AND r.archivo_origen IN (SELECT DISTINCT archivo_origen FROM stg.registros WHERE lote_id = p_lote)
           AND NOT EXISTS (SELECT 1 FROM stg.registros s WHERE s.lote_id = p_lote AND s.row_hash = r.row_hash);
        GET DIAGNOSTICS v_del = ROW_COUNT;
    END IF;

    -- 4) Upsert de hechos por hash de contenido (sin duplicados)
    WITH src AS (
        SELECT s.*, m.maquina_id, COALESCE(t.turno_id, 0) AS turno_id, COALESCE(o.operario_id, 0) AS operario_id,
               COALESCE(r.referencia_id, 0) AS referencia_id, tp.tipo_paro_id
          FROM stg.registros s
          JOIN oee.dim_maquina m ON m.nombre = s.maquina
          LEFT JOIN oee.dim_turno t ON t.nombre = s.turno
          LEFT JOIN oee.dim_operario o ON o.nombre = s.operario
          LEFT JOIN oee.dim_referencia r ON r.nombre = s.referencia
          LEFT JOIN oee.dim_tipo_paro_maquina tp ON tp.nombre = s.tipo_paro_maquina
         WHERE s.lote_id = p_lote
    ), up AS (
        INSERT INTO oee.registros_produccion AS t
               (row_hash, fecha, maquina_id, turno_id, operario_id, referencia_id, tipo_registro,
                pacas_producidas, horas_programadas, horas_no_programadas, tipo_paro_id,
                observacion, observacion_paro, calidad_dato, archivo_origen, fila_origen, lote_id)
        SELECT row_hash, fecha, maquina_id, turno_id, operario_id, referencia_id, tipo_registro,
               pacas, horas_programadas, horas_no_programadas, tipo_paro_id,
               observacion, observacion_paro, calidad_dato, archivo_origen, fila_origen, p_lote
          FROM src
        ON CONFLICT (row_hash) DO UPDATE
           SET observacion = EXCLUDED.observacion, observacion_paro = EXCLUDED.observacion_paro,
               fila_origen = EXCLUDED.fila_origen, lote_id = EXCLUDED.lote_id
         WHERE (t.observacion, t.observacion_paro, t.fila_origen) IS DISTINCT FROM
               (EXCLUDED.observacion, EXCLUDED.observacion_paro, EXCLUDED.fila_origen)
        RETURNING (xmax = 0) AS fue_insert
    )
    SELECT count(*) FILTER (WHERE fue_insert), count(*) FILTER (WHERE NOT fue_insert) INTO v_ins, v_upd FROM up;

    -- 5) Detalle de paros de los registros que aún no lo tienen (idempotente)
    INSERT INTO oee.detalle_paros_produccion (registro_id, motivo_id, subcodigo_id, minutos, area_involucrada, personal_involucrado)
    SELECT r.registro_id, p.motivo_id, sc.subcodigo_id, p.minutos,
           CASE WHEN p.area_involucrada IN ('Operarios', 'Personal_de_mantenimiento') THEN p.area_involucrada END,
           p.personal_involucrado
      FROM stg.paros p
      JOIN oee.registros_produccion r ON r.row_hash = p.row_hash
      LEFT JOIN oee.dim_subcodigo_paro sc ON sc.motivo_id = p.motivo_id AND sc.clave = p.subcodigo
     WHERE p.lote_id = p_lote
       AND NOT EXISTS (SELECT 1 FROM oee.detalle_paros_produccion d WHERE d.registro_id = r.registro_id);

    -- 6) Cierre del lote y limpieza del staging
    DELETE FROM stg.paros WHERE lote_id = p_lote;
    DELETE FROM stg.registros WHERE lote_id = p_lote;
    UPDATE etl.lotes
       SET estado = 'OK', finalizado_en = now(), filas_insertadas = v_ins, filas_actualizadas = v_upd,
           filas_eliminadas = v_del,
           mensaje = format('insertadas=%s actualizadas=%s eliminadas=%s', v_ins, v_upd, v_del)
     WHERE lote_id = p_lote;
END $$;
