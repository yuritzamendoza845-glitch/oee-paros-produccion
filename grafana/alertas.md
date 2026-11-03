# Alertas tempranas (Grafana Unified Alerting)

Crear en *Alerting → Alert rules* sobre el datasource `PostgreSQL-OEE`. Evaluación cada 15 min.
Todas leen vistas ya calculadas; los umbrales son **puntos de partida** a validar con Mantenimiento/Producción.

| # | Alerta | Consulta (Query A, formato *Table*) | Condición | Para |
|---|--------|--------------------------------------|-----------|------|
| 1 | OEE bajo (últimos 3 días) | `SELECT maquina, sum(pacas_buenas)/NULLIF(sum(pacas_ideales_planificadas),0) AS oee FROM oee.v_oee_diario WHERE fecha >= current_date - 3 GROUP BY 1` | `oee < 0.55` | 30 m |
| 2 | Cuello de botella: paro no planificado alto hoy | `SELECT maquina, sum(horas) AS horas FROM oee.v_paros_detalle WHERE fecha = current_date AND NOT es_planificado GROUP BY 1` | `horas > 3` | 0 m |
| 3 | Falla repetitiva (mismo subsistema, 7 días) | `SELECT maquina \|\| ' · ' \|\| subcodigo AS activo, count(*) AS eventos FROM oee.v_paros_detalle WHERE fecha >= current_date - 7 AND motivo_id IN (1,3,5) AND subcodigo <> 'Sin especificar' GROUP BY 1` | `eventos >= 8` | 0 m |
| 4 | **ETL caído / datos viejos** | `SELECT horas_desde_ultimo_ok FROM etl.v_estado_pipeline` | `> 26` (o sin datos) | 0 m |
| 5 | Errores de carga | `SELECT errores_24h FROM etl.v_estado_pipeline` | `> 0` | 0 m |

Contact point sugerido: correo del coordinador de mantenimiento (quien socializa el informe mensual según P-MTO-22 §4.1.8)
y un canal de Teams/Slack para producción. Agregue en cada regla la anotación `runbook_url` con el procedimiento P-MTO-22.
