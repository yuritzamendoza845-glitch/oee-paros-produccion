#!/usr/bin/env python3
"""Genera grafana/dashboards/oee_operativo.json (tablero provisionable por archivo)."""
import json
from pathlib import Path

DS = {"type": "grafana-postgresql-datasource", "uid": "pg-oee"}
VAR_MAQ = "('${maquina:csv}')"        # se usa con IN (...) mediante format raw abajo
FILT_MAQ = "maquina IN ($maquina)"    # variable multi-valor con includeAll


def q(sql, fmt="time_series"):
    return [{"datasource": DS, "refId": "A", "format": fmt, "rawQuery": True, "editorMode": "code", "rawSql": sql}]


def stat(pid, title, sql, x, y, w=4, h=4, unit="percentunit", thr=(0.6, 0.75, 0.85), inv=False):
    steps = [{"color": "red", "value": None}, {"color": "orange", "value": thr[0]},
             {"color": "yellow", "value": thr[1]}, {"color": "green", "value": thr[2]}]
    return {"id": pid, "type": "gauge", "title": title, "datasource": DS, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": q(sql, "table"),
            "fieldConfig": {"defaults": {"unit": unit, "min": 0, "max": 1, "thresholds": {"mode": "absolute", "steps": steps}}},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "showThresholdMarkers": True}}


RANGO = "fecha BETWEEN $__timeFrom()::date AND $__timeTo()::date"
AGG = lambda col, den: f"SELECT sum({col}) / NULLIF(sum({den}), 0) AS valor FROM oee.v_oee_diario WHERE {RANGO} AND {FILT_MAQ}"

panels = [
    stat(1, "OEE", "SELECT sum(pacas_buenas) / NULLIF(sum(pacas_ideales_planificadas),0) AS valor FROM oee.v_oee_diario WHERE " + RANGO + " AND " + FILT_MAQ, 0, 0),
    stat(2, "Disponibilidad", AGG("min_operativos", "min_planificados"), 4, 0),
    stat(3, "Rendimiento", AGG("pacas_producidas", "pacas_ideales_operativas"), 8, 0, thr=(0.6, 0.8, 0.9)),
    stat(4, "Calidad", AGG("pacas_buenas", "pacas_producidas"), 12, 0, thr=(0.9, 0.95, 0.98)),
    {"id": 5, "type": "stat", "title": "Pacas producidas", "datasource": DS, "gridPos": {"x": 16, "y": 0, "w": 4, "h": 4},
     "targets": q("SELECT sum(pacas_producidas) AS valor FROM oee.v_oee_diario WHERE " + RANGO + " AND " + FILT_MAQ, "table"),
     "fieldConfig": {"defaults": {"unit": "none", "decimals": 0}}, "options": {"colorMode": "none"}},
    {"id": 6, "type": "stat", "title": "Horas de paro no planificado", "datasource": DS, "gridPos": {"x": 20, "y": 0, "w": 4, "h": 4},
     "targets": q("SELECT sum(min_paro_no_planificado)/60.0 AS valor FROM oee.v_oee_diario WHERE " + RANGO + " AND " + FILT_MAQ, "table"),
     "fieldConfig": {"defaults": {"unit": "h", "decimals": 1, "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]}}}},
    {"id": 7, "type": "timeseries", "title": "OEE diario por máquina", "datasource": DS, "gridPos": {"x": 0, "y": 4, "w": 16, "h": 9},
     "targets": q("SELECT fecha AS time, maquina AS metric, oee AS value FROM oee.v_oee_diario WHERE $__timeFilter(fecha) AND " + FILT_MAQ + " ORDER BY 1"),
     "fieldConfig": {"defaults": {"unit": "percentunit", "min": 0, "max": 1.2, "custom": {"spanNulls": True, "lineWidth": 1, "fillOpacity": 8}}}},
    {"id": 8, "type": "bargauge", "title": "OEE por máquina (periodo)", "datasource": DS, "gridPos": {"x": 16, "y": 4, "w": 8, "h": 9},
     "targets": q("SELECT maquina, sum(pacas_buenas)/NULLIF(sum(pacas_ideales_planificadas),0) AS oee FROM oee.v_oee_diario WHERE " + RANGO + " AND " + FILT_MAQ + " GROUP BY 1 ORDER BY 1", "table"),
     "fieldConfig": {"defaults": {"unit": "percentunit", "min": 0, "max": 1, "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "yellow", "value": 0.6}, {"color": "green", "value": 0.75}]}}},
     "options": {"orientation": "horizontal", "displayMode": "gradient"}},
    {"id": 9, "type": "barchart", "title": "Pareto de paros no planificados (horas)", "datasource": DS, "gridPos": {"x": 0, "y": 13, "w": 12, "h": 10},
     "targets": q("SELECT motivo_etiqueta AS motivo, sum(horas) AS horas FROM oee.v_paros_detalle WHERE " + RANGO + " AND " + FILT_MAQ + " AND NOT es_planificado GROUP BY 1 ORDER BY 2 DESC LIMIT 12", "table"),
     "fieldConfig": {"defaults": {"unit": "h", "decimals": 1}}, "options": {"orientation": "horizontal", "xField": "motivo", "legend": {"showLegend": False}}},
    {"id": 10, "type": "table", "title": "Pareto con % acumulado (regla 80/20)", "datasource": DS, "gridPos": {"x": 12, "y": 13, "w": 12, "h": 10},
     "targets": q("SELECT posicion AS \"#\", motivo, horas, pct AS \"%\", pct_acumulado AS \"% acum.\", clase_abc AS \"ABC\" FROM oee.fn_pareto_paros($__timeFrom()::date, $__timeTo()::date, NULL, true)", "table"),
     "fieldConfig": {"defaults": {}, "overrides": [
         {"matcher": {"id": "byName", "options": "%"}, "properties": [{"id": "unit", "value": "percentunit"}]},
         {"matcher": {"id": "byName", "options": "% acum."}, "properties": [{"id": "unit", "value": "percentunit"}, {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "gradient"}}, {"id": "min", "value": 0}, {"id": "max", "value": 1}]}]}},
    {"id": 11, "type": "timeseries", "title": "Cuello de botella: horas de paro no planificado por día y área", "datasource": DS, "gridPos": {"x": 0, "y": 23, "w": 16, "h": 8},
     "targets": q("SELECT fecha AS time, area_impacto AS metric, sum(horas) AS value FROM oee.v_paros_detalle WHERE $__timeFilter(fecha) AND " + FILT_MAQ + " AND NOT es_planificado GROUP BY 1, 2 ORDER BY 1"),
     "fieldConfig": {"defaults": {"unit": "h", "custom": {"drawStyle": "bars", "stacking": {"mode": "normal"}, "fillOpacity": 70}}}},
    {"id": 12, "type": "table", "title": "Frescura del pipeline ETL", "datasource": DS, "gridPos": {"x": 16, "y": 23, "w": 8, "h": 8},
     "targets": q("SELECT ultimo_lote_ok, round(horas_desde_ultimo_ok::numeric,1) AS horas_desde_ultimo_ok, errores_24h, ultima_fecha_dato FROM etl.v_estado_pipeline", "table"),
     "fieldConfig": {"defaults": {}, "overrides": [{"matcher": {"id": "byName", "options": "horas_desde_ultimo_ok"}, "properties": [{"id": "thresholds", "value": {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "orange", "value": 8}, {"color": "red", "value": 26}]}}, {"id": "custom.cellOptions", "value": {"type": "color-background"}}]}]}},
]

dash = {
    "uid": "oee-operativo", "title": "OEE y paros — Vinilos y témperas", "tags": ["oee", "produccion", "vinilos"],
    "schemaVersion": 39, "version": 1, "editable": True, "timezone": "America/Bogota",
    "refresh": "5m", "time": {"from": "now-30d", "to": "now"},
    "description": "Disponibilidad, rendimiento y calidad desde PostgreSQL (vistas oee.v_*). Si el periodo no tiene datos, amplíe el rango de tiempo.",
    "templating": {"list": [{
        "name": "maquina", "label": "Máquina", "type": "query", "datasource": DS, "multi": True, "includeAll": True,
        "query": "SELECT nombre FROM oee.dim_maquina WHERE activa ORDER BY 1", "refresh": 1, "sort": 1,
        "current": {"text": "All", "value": "$__all"}}]},
    "panels": panels, "annotations": {"list": []},
}
dest = Path(__file__).parent / "dashboards" / "oee_operativo.json"
dest.write_text(json.dumps(dash, ensure_ascii=False, indent=2), encoding="utf-8")
print("escrito", dest, len(panels), "paneles")
