-- Pruebas de las reglas de negocio. Se ejecutan dentro de una transacción que se revierte (ROLLBACK).
--   psql -d oee -v ON_ERROR_STOP=1 -f 06_pruebas.sql      => debe terminar con "TODAS LAS PRUEBAS PASARON"
BEGIN;
DO $$
DECLARE
  v_reg bigint; v_det bigint; v_ok boolean; v_min numeric;
BEGIN
  INSERT INTO oee.registros_produccion (row_hash, fecha, maquina_id, tipo_registro, pacas_producidas, horas_programadas)
  VALUES (repeat('a',40), '2025-03-01', 1, 'PRODUCCION', 50, 8) RETURNING registro_id INTO v_reg;

  -- T1: minutos = fin - inicio (el trigger impone la duración)
  INSERT INTO oee.detalle_paros_produccion (registro_id, motivo_id, minutos, inicio, fin)
  VALUES (v_reg, 5, 999, '2025-03-01 08:00-05', '2025-03-01 08:30-05') RETURNING detalle_id, minutos INTO v_det, v_min;
  ASSERT v_min = 30, 'T1 falló: minutos debía ser 30, fue ' || v_min;

  -- T2: solapamiento en la misma máquina => error 23P01
  v_ok := false;
  BEGIN
    INSERT INTO oee.detalle_paros_produccion (registro_id, motivo_id, minutos, inicio, fin)
    VALUES (v_reg, 1, 1, '2025-03-01 08:15-05', '2025-03-01 08:45-05');
  EXCEPTION WHEN exclusion_violation THEN v_ok := true; END;
  ASSERT v_ok, 'T2 falló: se permitió un paro solapado';

  -- T3: fin <= inicio => check_violation
  v_ok := false;
  BEGIN
    INSERT INTO oee.detalle_paros_produccion (registro_id, motivo_id, minutos, inicio, fin)
    VALUES (v_reg, 1, 1, '2025-03-01 10:00-05', '2025-03-01 09:00-05');
  EXCEPTION WHEN check_violation THEN v_ok := true; END;
  ASSERT v_ok, 'T3 falló: se permitió fin antes de inicio';

  -- T4: totales del registro se recalculan (planificado vs no planificado)
  INSERT INTO oee.detalle_paros_produccion (registro_id, motivo_id, minutos) VALUES (v_reg, 17, 10);
  ASSERT (SELECT paro_no_planificado_min FROM oee.registros_produccion WHERE registro_id = v_reg) = 30, 'T4a falló';
  ASSERT (SELECT paro_planificado_min   FROM oee.registros_produccion WHERE registro_id = v_reg) = 10, 'T4b falló';

  -- T5: paros que exceden el turno marcan el registro como REVISAR
  INSERT INTO oee.detalle_paros_produccion (registro_id, motivo_id, minutos) VALUES (v_reg, 6, 600);
  ASSERT (SELECT calidad_dato FROM oee.registros_produccion WHERE registro_id = v_reg) = 'REVISAR', 'T5 falló';

  -- T6: subcódigo de otro código de paro es rechazado
  v_ok := false;
  BEGIN
    INSERT INTO oee.detalle_paros_produccion (registro_id, motivo_id, subcodigo_id, minutos)
    SELECT v_reg, 5, subcodigo_id, 1 FROM oee.dim_subcodigo_paro WHERE motivo_id = 3 LIMIT 1;
  EXCEPTION WHEN check_violation THEN v_ok := true; END;
  ASSERT v_ok, 'T6 falló: subcódigo cruzado aceptado';

  -- T7: no conformes <= producidas
  v_ok := false;
  BEGIN UPDATE oee.registros_produccion SET pacas_no_conformes = 999 WHERE registro_id = v_reg;
  EXCEPTION WHEN check_violation THEN v_ok := true; END;
  ASSERT v_ok, 'T7 falló';

  -- T8: auditoría registra cambios de negocio
  UPDATE oee.registros_produccion SET pacas_producidas = 55 WHERE registro_id = v_reg;
  ASSERT EXISTS (SELECT 1 FROM audit.log_cambios WHERE tabla = 'oee.registros_produccion' AND pk = v_reg::text AND operacion = 'UPDATE'), 'T8 falló';

  -- T9: idempotencia por row_hash
  v_ok := false;
  BEGIN INSERT INTO oee.registros_produccion (row_hash, fecha, maquina_id, tipo_registro, pacas_producidas, horas_programadas)
        VALUES (repeat('a',40), '2025-03-01', 1, 'PRODUCCION', 50, 8);
  EXCEPTION WHEN unique_violation THEN v_ok := true; END;
  ASSERT v_ok, 'T9 falló: hash duplicado aceptado';

  RAISE NOTICE 'TODAS LAS PRUEBAS PASARON';
END $$;
ROLLBACK;
