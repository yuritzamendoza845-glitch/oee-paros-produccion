#!/usr/bin/env python3
"""Genera las tablas del modelo en estrella (CSV) a partir de database/base_datos_oee.sqlite.
Replica la lógica de sql/04_vistas_oee.sql (PostgreSQL). Uso: python generar_datos.py [RUTA_SQLITE] [CARPETA_SALIDA]
Por defecto lee ../database/base_datos_oee.sqlite y escribe en ./datos
Despues ejecute incrustar_datos.py para que el modelo de Power BI use los CSV nuevos."""
import sqlite3, sys, os
import pandas as pd

aqui = os.path.dirname(os.path.abspath(__file__))
db = sys.argv[1] if len(sys.argv) > 1 else os.path.join(aqui, "..", "database", "base_datos_oee.sqlite")
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(aqui, "datos")
os.makedirs(out, exist_ok=True)
c = sqlite3.connect(db)
q = lambda s: pd.read_sql_query(s, c)

# ---------- Fact_Turno (equivale a oee.v_oee_turno) ----------
h = q("""
WITH base AS (
  SELECT r.*, MAX(r.tipo_registro='PRODUCCION') OVER (PARTITION BY r.fecha, r.maquina_id, r.turno_id, r.operario_id, r.referencia_id) AS en_alcance,
         COALESCE(m1.meta_pacas_hora, m0.meta_pacas_hora) AS meta,
         CASE WHEN m1.meta_pacas_hora IS NOT NULL THEN m1.origen ELSE m0.origen END AS origen_meta
    FROM registros_produccion r
    LEFT JOIN meta_produccion m1 ON m1.maquina_id=r.maquina_id AND m1.referencia_id=r.referencia_id
    LEFT JOIN meta_produccion m0 ON m0.maquina_id=r.maquina_id AND m0.referencia_id=0
   WHERE r.calidad_dato <> 'POSIBLE_DUPLICADO')
SELECT fecha, maquina_id, turno_id, operario_id, referencia_id,
       MAX(meta) AS meta_pacas_hora, MAX(origen_meta) AS origen_meta,
       SUM(horas_programadas*60) AS min_programados,
       SUM(paro_planificado_min) AS min_paro_planificado,
       SUM(paro_no_planificado_min) AS bruto,
       SUM(COALESCE(pacas_producidas,0)) AS pacas_producidas,
       SUM(COALESCE(pacas_no_conformes,0)) AS pacas_no_conformes,
       SUM(CASE WHEN tipo_registro='PRODUCCION' THEN horas_no_programadas ELSE 0 END) AS horas_no_programadas,
       MAX(calidad_dato='REVISAR') AS requiere_revision
  FROM base WHERE en_alcance=1
 GROUP BY fecha, maquina_id, turno_id, operario_id, referencia_id""")
h["min_planificados"] = (h.min_programados - h.min_paro_planificado).clip(lower=0)
h["min_paro_no_planificado"] = h[["bruto", "min_planificados"]].min(axis=1)
h["min_operativos"] = h.min_planificados - h.min_paro_no_planificado
h["pacas_buenas"] = h.pacas_producidas - h.pacas_no_conformes
h["pacas_ideales_operativas"] = h.min_operativos / 60 * h.meta_pacas_hora
h["pacas_ideales_planificadas"] = h.min_planificados / 60 * h.meta_pacas_hora
h["requiere_revision"] = h.requiere_revision.astype(bool)
cols = ["fecha","maquina_id","turno_id","operario_id","referencia_id","origen_meta","meta_pacas_hora","min_programados",
        "min_paro_planificado","min_planificados","min_paro_no_planificado","min_operativos","pacas_producidas",
        "pacas_no_conformes","pacas_buenas","pacas_ideales_operativas","pacas_ideales_planificadas",
        "horas_no_programadas","requiere_revision"]
h[cols].round(4).to_csv(f"{out}/Fact_Turno.csv", index=False)

# ---------- Fact_Paros (equivale a oee.v_paros_detalle) ----------
p = q("""
SELECT d.detalle_id, r.fecha, r.maquina_id, r.turno_id, r.operario_id, r.referencia_id, d.motivo_id,
       sc.clave AS subcodigo_clave, COALESCE(sc.nombre,'Sin especificar') AS subcodigo, d.area_involucrada,
       d.minutos, d.minutos/60.0 AS horas
  FROM detalle_paros_produccion d
  JOIN registros_produccion r ON r.registro_id=d.registro_id AND r.calidad_dato<>'POSIBLE_DUPLICADO'
  LEFT JOIN dim_subcodigo_paro sc ON sc.subcodigo_id=d.subcodigo_id""")
p.round(4).to_csv(f"{out}/Fact_Paros.csv", index=False)

# ---------- Fact_HorasNoProgramadas (v_horas_no_programadas, SIN el filtro horas_no_programadas>0) ----------
n = q("""
SELECT r.fecha, r.maquina_id, COALESCE(tp.nombre,'Sin causa registrada') AS causa,
       COALESCE(tp.pierde_disponibilidad,0) AS causa_operativa,
       SUM(r.horas_no_programadas) AS horas_no_programadas, SUM(r.horas_programadas) AS horas_programadas
  FROM registros_produccion r LEFT JOIN dim_tipo_paro_maquina tp ON tp.tipo_paro_id=r.tipo_paro_id
 WHERE r.tipo_registro='PRODUCCION' AND r.calidad_dato<>'POSIBLE_DUPLICADO'
 GROUP BY 1,2,3,4""")
n["causa_operativa"] = n.causa_operativa.astype(bool)
n.round(4).to_csv(f"{out}/Fact_HorasNoProgramadas.csv", index=False)

# ---------- Dimensiones ----------
f = pd.DataFrame({"fecha": pd.date_range("2022-01-01", "2025-12-31")})
meses = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
dias = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
f["anio"] = f.fecha.dt.year; f["trimestre"] = f.fecha.dt.quarter; f["mes"] = f.fecha.dt.month
f["nombre_mes"] = f.mes.map(lambda m: meses[m-1]); f["anio_mes"] = f.fecha.dt.strftime("%Y-%m")
f["semana_iso"] = f.fecha.dt.isocalendar().week.astype(int); f["dia_semana"] = f.fecha.dt.dayofweek + 1
f["nombre_dia"] = f.dia_semana.map(lambda d: dias[d-1]); f["es_fin_semana"] = f.dia_semana >= 6
f["fecha"] = f.fecha.dt.strftime("%Y-%m-%d"); f.to_csv(f"{out}/Dim_Fecha.csv", index=False)

q("select maquina_id, nombre as Máquina, linea from dim_maquina").to_csv(f"{out}/Dim_Maquina.csv", index=False)
q("select turno_id, nombre as Turno, horas_nominales from dim_turno").to_csv(f"{out}/Dim_Turno.csv", index=False)
q("select operario_id, nombre as 'Operaria/o' from dim_operario").to_csv(f"{out}/Dim_Operaria.csv", index=False)
r = q("select referencia_id, nombre as Referencia, marca as Marca, volumen_cc as 'Volumen (cc)', num_colores as Colores from dim_referencia")
r[["Volumen (cc)", "Colores"]] = r[["Volumen (cc)", "Colores"]].astype("Int64")
r.to_csv(f"{out}/Dim_Referencia.csv", index=False)
q("""select m.motivo_id, m.nombre as Motivo, a.nombre as 'Área de impacto',
            '[' || substr('0'||m.motivo_id, -2) || '] ' || m.nombre as Etiqueta,
            m.es_planificado as 'Es planificado', m.categoria_oee as 'Categoría OEE'
       from dim_motivo_paro m join dim_area_impacto a on a.area_id=m.area_id""").assign(**{}).pipe(
    lambda d: d.assign(**{"Es planificado": d["Es planificado"].astype(bool)})).to_csv(f"{out}/Dim_MotivoParo.csv", index=False)
q("select * from meta_produccion").to_csv(f"{out}/Meta_Produccion.csv", index=False)
print("OK ->", out)
