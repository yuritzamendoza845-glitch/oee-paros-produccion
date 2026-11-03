-- =====================================================================================
-- 04_vistas_oee.sql | Capa semántica en PostgreSQL consumida por Grafana y Power BI
--
-- Definiciones (todas en minutos; ver docs/03_reglas_oee.md):
--   Tiempo programado   = horas_programadas × 60                (columna "Horas trabajadas" del libro)
--   Tiempo planificado  = programado − paros planificados       (códigos 15,16,17,18: es_planificado)
--   Tiempo operativo    = planificado − paros NO planificados   (códigos 1–14)
--   Disponibilidad (A)  = operativo / planificado
--   Rendimiento    (P)  = pacas producidas / (operativo/60 × meta pacas/hora)
--   Calidad        (Q)  = (pacas − no conformes) / pacas
--   OEE = A × P × Q  =  pacas buenas / (planificado/60 × meta)
--   Las "horas no trabajadas" (calendario fuera de programación) NO entran al OEE: alimentan la
--   utilización de calendario (TEEP) y su causa (Tipo de paro).
-- =====================================================================================

-- 1) Hechos a nivel de fila del libro, con alcance OEE y meta resuelta ----------------------
CREATE OR REPLACE VIEW oee.v_oee_hechos AS
WITH base AS (
    SELECT r.*,
           bool_or(r.tipo_registro = 'PRODUCCION')
               OVER (PARTITION BY r.fecha, r.maquina_id, r.turno_id, r.operario_id, r.referencia_id) AS grupo_con_produccion
      FROM oee.registros_produccion r
     WHERE r.calidad_dato <> 'POSIBLE_DUPLICADO'          -- las copias exactas no doblan la producción
)
SELECT b.registro_id, b.fecha, b.maquina_id, b.turno_id, b.operario_id, b.referencia_id,
       b.tipo_registro, b.calidad_dato,
       b.grupo_con_produccion                                   AS en_alcance_oee,
       COALESCE(m1.meta_pacas_hora, m0.meta_pacas_hora)         AS meta_pacas_hora,
       CASE WHEN m1.meta_pacas_hora IS NOT NULL THEN m1.origen ELSE m0.origen END AS origen_meta,
       b.horas_programadas * 60                                 AS min_programados,
       CASE WHEN b.grupo_con_produccion THEN b.paro_planificado_min    ELSE 0 END AS min_paro_planificado,
       CASE WHEN b.grupo_con_produccion THEN b.paro_no_planificado_min ELSE 0 END AS min_paro_no_planificado,
       COALESCE(b.pacas_producidas, 0)                          AS pacas_producidas,
       b.pacas_no_conformes,
       CASE WHEN b.tipo_registro = 'PRODUCCION' THEN b.horas_no_programadas ELSE 0 END AS horas_no_programadas,
       b.tipo_paro_id
  FROM base b
  LEFT JOIN oee.meta_produccion m1 ON m1.maquina_id = b.maquina_id AND m1.referencia_id = b.referencia_id
  LEFT JOIN oee.meta_produccion m0 ON m0.maquina_id = b.maquina_id AND m0.referencia_id = 0;

-- 2) Grano turno-operaria-referencia (une producción + sus paros complementarios) ----------
CREATE OR REPLACE VIEW oee.v_oee_turno AS
WITH g AS (
    SELECT fecha, maquina_id, turno_id, operario_id, referencia_id,
           max(meta_pacas_hora)                       AS meta_pacas_hora,
           sum(min_programados)                       AS min_programados,
           sum(min_paro_planificado)                  AS min_paro_planificado,
           sum(min_paro_no_planificado)               AS min_paro_no_planificado_bruto,
           sum(pacas_producidas)                      AS pacas_producidas,
           sum(pacas_no_conformes)                    AS pacas_no_conformes,
           sum(horas_no_programadas)                  AS horas_no_programadas,
           bool_or(calidad_dato = 'REVISAR')          AS requiere_revision
      FROM oee.v_oee_hechos
     WHERE en_alcance_oee
     GROUP BY fecha, maquina_id, turno_id, operario_id, referencia_id
), c AS (   -- recorta para que ningún componente de tiempo sea negativo (registros marcados REVISAR)
    SELECT g.*,
           GREATEST(min_programados - min_paro_planificado, 0)                         AS min_planificados,
           LEAST(min_paro_no_planificado_bruto, GREATEST(min_programados - min_paro_planificado, 0)) AS min_paro_no_planificado
      FROM g
)
SELECT c.fecha, c.maquina_id, c.turno_id, c.operario_id, c.referencia_id,
       c.min_programados, c.min_paro_planificado, c.min_planificados, c.min_paro_no_planificado,
       c.min_planificados - c.min_paro_no_planificado                                   AS min_operativos,
       c.pacas_producidas, c.pacas_no_conformes, c.pacas_producidas - c.pacas_no_conformes AS pacas_buenas,
       c.meta_pacas_hora,
       (c.min_planificados - c.min_paro_no_planificado) / 60.0 * c.meta_pacas_hora       AS pacas_ideales_operativas,
       c.min_planificados / 60.0 * c.meta_pacas_hora                                      AS pacas_ideales_planificadas,
       c.horas_no_programadas, c.requiere_revision,
       -- indicadores a este grano
       round((c.min_planificados - c.min_paro_no_planificado) / NULLIF(c.min_planificados, 0), 4) AS disponibilidad,
       round(c.pacas_producidas / NULLIF((c.min_planificados - c.min_paro_no_planificado) / 60.0 * c.meta_pacas_hora, 0), 4) AS rendimiento,
       round((c.pacas_producidas - c.pacas_no_conformes) / NULLIF(c.pacas_producidas, 0), 4)       AS calidad,
       round((c.pacas_producidas - c.pacas_no_conformes) / NULLIF(c.min_planificados / 60.0 * c.meta_pacas_hora, 0), 4) AS oee
  FROM c;

-- 3) Agregados (los ratios se recalculan desde sumas: nunca promedian porcentajes) -----------
CREATE OR REPLACE VIEW oee.v_oee_diario AS
SELECT t.fecha, m.nombre AS maquina, t.maquina_id,
       sum(min_programados) AS min_programados, sum(min_planificados) AS min_planificados,
       sum(min_paro_planificado) AS min_paro_planificado, sum(min_paro_no_planificado) AS min_paro_no_planificado,
       sum(min_operativos) AS min_operativos, sum(pacas_producidas) AS pacas_producidas,
       sum(pacas_buenas) AS pacas_buenas, sum(pacas_ideales_operativas) AS pacas_ideales_operativas,
       sum(pacas_ideales_planificadas) AS pacas_ideales_planificadas, sum(horas_no_programadas) AS horas_no_programadas,
       round(sum(min_operativos) / NULLIF(sum(min_planificados), 0), 4)                    AS disponibilidad,
       round(sum(pacas_producidas) / NULLIF(sum(pacas_ideales_operativas), 0), 4)           AS rendimiento,
       round(sum(pacas_buenas) / NULLIF(sum(pacas_producidas), 0), 4)                       AS calidad,
       round(sum(pacas_buenas) / NULLIF(sum(pacas_ideales_planificadas), 0), 4)             AS oee
  FROM oee.v_oee_turno t JOIN oee.dim_maquina m USING (maquina_id)
 GROUP BY t.fecha, m.nombre, t.maquina_id;

CREATE OR REPLACE VIEW oee.v_oee_mensual AS
SELECT date_trunc('month', fecha)::date AS mes, maquina, maquina_id,
       sum(min_planificados) AS min_planificados, sum(min_paro_no_planificado) AS min_paro_no_planificado,
       sum(min_operativos) AS min_operativos, sum(pacas_producidas) AS pacas_producidas, sum(pacas_buenas) AS pacas_buenas,
       round(sum(min_operativos) / NULLIF(sum(min_planificados), 0), 4)             AS disponibilidad,
       round(sum(pacas_producidas) / NULLIF(sum(pacas_ideales_operativas), 0), 4)    AS rendimiento,
       round(sum(pacas_buenas) / NULLIF(sum(pacas_producidas), 0), 4)                AS calidad,
       round(sum(pacas_buenas) / NULLIF(sum(pacas_ideales_planificadas), 0), 4)      AS oee
  FROM oee.v_oee_diario
 GROUP BY 1, maquina, maquina_id;

-- 4) Paros: todos los minutos registrados (incluye los de turnos sin fila de producción) -----
CREATE OR REPLACE VIEW oee.v_paros_detalle AS
SELECT d.detalle_id, r.fecha, r.maquina_id, ma.nombre AS maquina, r.turno_id, tu.nombre AS turno,
       r.operario_id, op.nombre AS operario, r.referencia_id, rf.nombre AS referencia,
       d.motivo_id, mo.nombre AS motivo, '[' || lpad(mo.motivo_id::text, 2, '0') || '] ' || mo.nombre AS motivo_etiqueta,
       ai.nombre AS area_impacto, mo.es_planificado, mo.categoria_oee,
       sc.clave AS subcodigo_clave, COALESCE(sc.nombre, 'Sin especificar') AS subcodigo,
       d.area_involucrada, d.personal_involucrado, d.minutos, d.minutos / 60.0 AS horas
  FROM oee.detalle_paros_produccion d
  JOIN oee.registros_produccion r ON r.registro_id = d.registro_id AND r.calidad_dato <> 'POSIBLE_DUPLICADO'
  JOIN oee.dim_maquina ma ON ma.maquina_id = r.maquina_id
  JOIN oee.dim_turno tu ON tu.turno_id = r.turno_id
  JOIN oee.dim_operario op ON op.operario_id = r.operario_id
  JOIN oee.dim_referencia rf ON rf.referencia_id = r.referencia_id
  JOIN oee.dim_motivo_paro mo ON mo.motivo_id = d.motivo_id
  JOIN oee.dim_area_impacto ai ON ai.area_id = mo.area_id
  LEFT JOIN oee.dim_subcodigo_paro sc ON sc.subcodigo_id = d.subcodigo_id;

-- Pareto con % y % acumulado, parametrizable (Grafana/Power BI/psql)
CREATE OR REPLACE FUNCTION oee.fn_pareto_paros(
    p_desde date, p_hasta date, p_maquina text DEFAULT NULL, p_solo_no_planificados boolean DEFAULT true)
RETURNS TABLE (posicion int, motivo text, horas numeric, pct numeric, pct_acumulado numeric, clase_abc text)
LANGUAGE sql STABLE AS $$
    WITH t AS (
        SELECT motivo_etiqueta AS motivo, sum(horas) AS horas
          FROM oee.v_paros_detalle
         WHERE fecha BETWEEN p_desde AND p_hasta
           AND (p_maquina IS NULL OR maquina = p_maquina)
           AND (NOT p_solo_no_planificados OR NOT es_planificado)
         GROUP BY 1
    ), p AS (
        SELECT motivo, horas, horas / NULLIF(sum(horas) OVER (), 0) AS pct,
               sum(horas) OVER (ORDER BY horas DESC, motivo) / NULLIF(sum(horas) OVER (), 0) AS acum
          FROM t
    )
    SELECT (row_number() OVER (ORDER BY horas DESC, motivo))::int, motivo, round(horas, 2), round(pct, 4), round(acum, 4),
           CASE WHEN acum - pct < 0.80 THEN 'A' WHEN acum - pct < 0.95 THEN 'B' ELSE 'C' END
      FROM p ORDER BY horas DESC, motivo;
$$;

-- 5) Utilización de calendario (TEEP) y causa de las horas fuera de programación -------------
CREATE OR REPLACE VIEW oee.v_horas_no_programadas AS
SELECT r.fecha, ma.nombre AS maquina, COALESCE(tp.nombre, 'Sin causa registrada') AS causa,
       COALESCE(tp.pierde_disponibilidad, false) AS causa_operativa,    -- true: insumos/personal/calidad; false: demanda o planeación
       sum(r.horas_no_programadas) AS horas_no_programadas, sum(r.horas_programadas) AS horas_programadas
  FROM oee.registros_produccion r
  JOIN oee.dim_maquina ma USING (maquina_id)
  LEFT JOIN oee.dim_tipo_paro_maquina tp USING (tipo_paro_id)
 WHERE r.tipo_registro = 'PRODUCCION' AND r.calidad_dato <> 'POSIBLE_DUPLICADO' AND r.horas_no_programadas > 0
 GROUP BY 1, 2, 3, 4;

-- 6) Calidad de datos: lo que el ETL cargó pero que conviene revisar -------------------------
CREATE OR REPLACE VIEW oee.v_calidad_datos AS
SELECT 'Registros marcados REVISAR (paros > turno)'          AS control, count(*)::bigint AS filas FROM oee.registros_produccion WHERE calidad_dato = 'REVISAR'
UNION ALL SELECT 'Posibles duplicados excluidos del OEE',       count(*) FROM oee.registros_produccion WHERE calidad_dato = 'POSIBLE_DUPLICADO'
UNION ALL SELECT 'Paros sin fila de producción (fuera del OEE, dentro del Pareto)', count(*) FROM oee.v_oee_hechos WHERE NOT en_alcance_oee
UNION ALL SELECT 'Registros de producción sin meta resuelta',   count(*) FROM oee.v_oee_hechos WHERE en_alcance_oee AND meta_pacas_hora IS NULL
UNION ALL SELECT 'Registros sin operaria / turno / referencia', count(*) FROM oee.registros_produccion WHERE operario_id = 0 OR turno_id = 0 OR referencia_id = 0
UNION ALL SELECT 'Subcódigo 1/3/5 sin especificar',             count(*) FROM oee.detalle_paros_produccion WHERE motivo_id IN (1, 3, 5) AND subcodigo_id IS NULL;

-- 7) Salud del pipeline (Grafana: panel de frescura / alerta de ETL caído) -------------------
CREATE OR REPLACE VIEW etl.v_estado_pipeline AS
SELECT (SELECT max(finalizado_en) FROM etl.lotes WHERE estado = 'OK')                               AS ultimo_lote_ok,
       EXTRACT(epoch FROM now() - (SELECT max(finalizado_en) FROM etl.lotes WHERE estado = 'OK')) / 3600.0 AS horas_desde_ultimo_ok,
       (SELECT count(*) FROM etl.lotes WHERE estado = 'ERROR' AND iniciado_en > now() - interval '24 hours') AS errores_24h,
       (SELECT max(fecha) FROM oee.registros_produccion)                                            AS ultima_fecha_dato;
