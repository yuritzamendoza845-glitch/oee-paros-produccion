-- GENERADO por etl/generate_seed.py — no editar a mano (edite etl/reglas.py y regenere).
-- Idempotente: re-ejecutable sin duplicar.
BEGIN;

INSERT INTO oee.dim_maquina (maquina_id, nombre) VALUES
  (1, 'Vinilos_1'),
  (2, 'Vinilos_2'),
  (3, 'Vinilos_3'),
  (4, 'Vinilos_4')
ON CONFLICT (maquina_id) DO NOTHING;

INSERT INTO oee.dim_turno (turno_id, nombre, hora_inicio, hora_fin, horas_nominales) VALUES
  (0, 'Sin dato', NULL, NULL, NULL),
  (1, '6am-2pm (Turno 1)', '06:00', '14:00', 8.0),
  (2, '2pm-10pm (Turno 2)', '14:00', '22:00', 8.0),
  (3, '10pm-6am (Turno 3)', '22:00', '06:00', 8.0),
  (4, '6am-4:30pm', '06:00', '16:30', 10.5),
  (5, '6am-6pm', '06:00', '18:00', 12.0),
  (6, '6pm-6am', '18:00', '06:00', 12.0)
ON CONFLICT (turno_id) DO NOTHING;

INSERT INTO oee.dim_operario (operario_id, nombre) VALUES (0, 'Sin dato') ON CONFLICT DO NOTHING;
INSERT INTO oee.dim_referencia (referencia_id, nombre) VALUES (0, 'Sin dato') ON CONFLICT DO NOTHING;

INSERT INTO oee.dim_area_impacto (nombre) VALUES
  ('Almacén de materias primas'),
  ('Calidad'),
  ('Mantenimiento'),
  ('Paro programado'),
  ('Producción')
ON CONFLICT (nombre) DO NOTHING;

INSERT INTO oee.dim_motivo_paro (motivo_id, nombre, area_id, es_planificado, categoria_oee)
SELECT v.id, v.nombre, a.area_id, v.plan, v.cat FROM (VALUES
  (1, 'Falla del sistema electromecánico y/o de control', 'Mantenimiento', false, 'AVERIA'),
  (2, 'Espera de soporte de mantenimiento', 'Mantenimiento', false, 'ESPERA'),
  (3, 'Novedad en los sistemas de potencia (aire, energía, vapor)', 'Mantenimiento', false, 'AVERIA'),
  (4, 'Mantenimiento preventivo', 'Mantenimiento', false, 'AVERIA'),
  (5, 'Ajuste operativo', 'Producción', false, 'AJUSTE'),
  (6, 'Limpieza por derrame operativo / tiempo sin reportar', 'Producción', false, 'AJUSTE'),
  (7, 'Alistamiento de máquina / cambio de referencia', 'Producción', false, 'CAMBIO_REFERENCIA'),
  (8, 'Capacitación / reunión', 'Producción', false, 'ORGANIZACIONAL'),
  (9, 'Falta de operario', 'Producción', false, 'ORGANIZACIONAL'),
  (10, 'Paro por ventaja / evacuación / calidad', 'Producción', false, 'AJUSTE'),
  (11, 'Reproceso', 'Producción', false, 'CALIDAD'),
  (12, 'Materia prima defectuosa', 'Calidad', false, 'CALIDAD'),
  (13, 'En espera por el aval del laboratorio de microbiología', 'Calidad', false, 'ESPERA'),
  (14, 'Falta de materia prima', 'Almacén de materias primas', false, 'ABASTECIMIENTO'),
  (15, 'Cambio de insumos (roscadores, o''ring, etiquetas)', 'Paro programado', true, 'PLANIFICADO'),
  (16, 'Alimentación y aseo de la zona de trabajo y la máquina', 'Paro programado', true, 'PLANIFICADO'),
  (17, 'Pausa activa', 'Paro programado', true, 'PLANIFICADO'),
  (18, 'Desinfección', 'Paro programado', true, 'PLANIFICADO')
) AS v(id, nombre, area, plan, cat) JOIN oee.dim_area_impacto a ON a.nombre = v.area
ON CONFLICT (motivo_id) DO NOTHING;

INSERT INTO oee.dim_subcodigo_paro (motivo_id, clave, nombre, nivel, clave_padre) VALUES
  (1, '1.1', 'Sistema alimentador de envases', 1, NULL),
  (1, '1.2', 'Sistema de dosificación', 1, NULL),
  (1, '1.3', 'Sistema de banda de entrada', 1, NULL),
  (1, '1.4', 'Sistema de tapado (transfer y pisador de tapa)', 1, NULL),
  (1, '1.5', 'Sistema de alimentación de tapa', 1, NULL),
  (1, '1.6', 'Sistema Video Jet', 1, NULL),
  (1, '1.7', 'Sistema de sujeción y roscadores', 1, NULL),
  (1, '1.8', 'Sistema etiquetadora', 1, NULL),
  (1, '1.1.A', 'Banda', 2, '1.1'),
  (1, '1.1.B', 'Motor', 2, '1.1'),
  (1, '1.1.C', 'Sensor', 2, '1.1'),
  (1, '1.2.A', 'Cambio de racores', 2, '1.2'),
  (1, '1.2.B', 'Ajuste de sensor', 2, '1.2'),
  (1, '1.2.C', 'Cambio de válvula', 2, '1.2'),
  (1, '1.2.D', 'Retenedores', 2, '1.2'),
  (1, '1.2.E', 'O''Ring', 2, '1.2'),
  (1, '1.3.A', 'Banda', 2, '1.3'),
  (1, '1.3.B', 'Motor', 2, '1.3'),
  (1, '1.4.A', 'Motor del transfer', 2, '1.4'),
  (1, '1.4.B', 'Pisador de tapa', 2, '1.4'),
  (1, '1.4.3', 'Sensor', 2, '1.4'),
  (1, '1.5.A', 'Banda', 2, '1.5'),
  (1, '1.5.B', 'Motor', 2, '1.5'),
  (1, '1.5.C', 'Sensor', 2, '1.5'),
  (1, '1.6.A', 'Fotocelda', 2, '1.6'),
  (1, '1.6.B', 'Sensor', 2, '1.6'),
  (1, '1.7.A', 'Banda de sujeción', 2, '1.7'),
  (1, '1.7.B', 'Roscadores', 2, '1.7'),
  (1, '1.8.A', 'Banda', 2, '1.8'),
  (1, '1.8.B', 'Motor', 2, '1.8'),
  (1, '1.8.C', 'Sensor', 2, '1.8'),
  (3, '3.1', 'Fallo en la subestación', 1, NULL),
  (3, '3.2', 'Fallo en la red pública', 1, NULL),
  (3, '3.3', 'Falla en la red neumática o el compresor', 1, NULL),
  (3, '3.4', 'Falla en la red de enfriamiento o chiller', 1, NULL),
  (3, '3.5', 'Falla en la red de vapor o caldera', 1, NULL),
  (5, '5.1', 'Sistema alimentador de envases', 1, NULL),
  (5, '5.2', 'Sistema de dosificación de pintura, frontal y posterior', 1, NULL),
  (5, '5.3', 'Banda transportadora de entrada', 1, NULL),
  (5, '5.4', 'Banda transportadora de salida', 1, NULL),
  (5, '5.5', 'Transfer y pisador de tapa', 1, NULL),
  (5, '5.6', 'Sistema alimentador de tapa y tobogán', 1, NULL),
  (5, '5.7', 'Video Jet', 1, NULL),
  (5, '5.8', 'Banda de sujeción y roscadores', 1, NULL),
  (5, '5.9', 'Sistema de etiquetado', 1, NULL),
  (5, '5.10', 'Purga de color', 1, NULL),
  (5, '5.11', 'Lavado de boquilla', 1, NULL)
ON CONFLICT (motivo_id, clave) DO NOTHING;

INSERT INTO oee.dim_tipo_paro_maquina (nombre, pierde_disponibilidad) VALUES
  ('Ajuste operativo', true),
  ('Alistamiento / cambio de referencia', true),
  ('Espera aval de laboratorio (microbiología)', true),
  ('Falta de materiales o materias primas', true),
  ('Falta de operario', true),
  ('Falta de programación (planeación)', false),
  ('Limpieza no programada', true),
  ('Materia prima o empaque no conforme', true),
  ('Novedad en servicios (aire, energía, vapor)', true),
  ('Paro de máquina (sin causa registrada)', false),
  ('Paro de máquina por ventas (sin demanda)', false),
  ('Paro por proceso anterior', true)
ON CONFLICT (nombre) DO NOTHING;

-- Calendario 2020-2030 (nombres de mes en español; no depende de lc_time del servidor)
INSERT INTO oee.dim_fecha (fecha, anio, trimestre, mes, nombre_mes, semana_iso, dia_semana, es_fin_semana)
SELECT d::date, EXTRACT(year FROM d), EXTRACT(quarter FROM d), EXTRACT(month FROM d),
       (ARRAY['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'])[EXTRACT(month FROM d)::int],
       EXTRACT(week FROM d), EXTRACT(isodow FROM d), EXTRACT(isodow FROM d) >= 6
FROM generate_series('2020-01-01'::date, '2030-12-31'::date, interval '1 day') AS d
ON CONFLICT (fecha) DO NOTHING;

COMMIT;
