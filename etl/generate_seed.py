#!/usr/bin/env python3
"""Genera sql/02_seed_catalogos.sql a partir de reglas.py (única fuente de verdad de los catálogos)."""
from pathlib import Path
import reglas as R

q = lambda s: "'" + str(s).replace("'", "''") + "'"
out = ["-- GENERADO por etl/generate_seed.py — no editar a mano (edite etl/reglas.py y regenere).",
       "-- Idempotente: re-ejecutable sin duplicar.", "BEGIN;", ""]

out.append("INSERT INTO oee.dim_maquina (maquina_id, nombre) VALUES")
out.append(",\n".join(f"  ({i}, {q(n)})" for i, n in enumerate(R.MAQUINAS, 1)))
out.append("ON CONFLICT (maquina_id) DO NOTHING;\n")

out.append("INSERT INTO oee.dim_turno (turno_id, nombre, hora_inicio, hora_fin, horas_nominales) VALUES")
rows = ["  (0, 'Sin dato', NULL, NULL, NULL)"] + [
    f"  ({i}, {q(n)}, {q(a)}, {q(b)}, {h})" for i, (n, a, b, h) in enumerate(R.TURNOS, 1)]
out.append(",\n".join(rows) + "\nON CONFLICT (turno_id) DO NOTHING;\n")

out.append("INSERT INTO oee.dim_operario (operario_id, nombre) VALUES (0, 'Sin dato') ON CONFLICT DO NOTHING;")
out.append("INSERT INTO oee.dim_referencia (referencia_id, nombre) VALUES (0, 'Sin dato') ON CONFLICT DO NOTHING;\n")

areas = sorted({m[2] for m in R.MOTIVOS})
out.append("INSERT INTO oee.dim_area_impacto (nombre) VALUES\n" + ",\n".join(f"  ({q(a)})" for a in areas) + "\nON CONFLICT (nombre) DO NOTHING;\n")

out.append("INSERT INTO oee.dim_motivo_paro (motivo_id, nombre, area_id, es_planificado, categoria_oee)\nSELECT v.id, v.nombre, a.area_id, v.plan, v.cat FROM (VALUES")
out.append(",\n".join(f"  ({i}, {q(n)}, {q(a)}, {str(p).lower()}, {q(c)})" for i, n, a, p, c in R.MOTIVOS))
out.append(") AS v(id, nombre, area, plan, cat) JOIN oee.dim_area_impacto a ON a.nombre = v.area\nON CONFLICT (motivo_id) DO NOTHING;\n")

sub = []
for cod, d in R.SUBCODIGOS.items():
    for clave, nombre in d.items():
        nivel = 1 if (cod != 1 or clave.count(".") == 1) else 2
        padre = ".".join(clave.split(".")[:2]) if (cod == 1 and nivel == 2) else None
        sub.append(f"  ({cod}, {q(clave)}, {q(nombre)}, {nivel}, {q(padre) if padre else 'NULL'})")
out.append("INSERT INTO oee.dim_subcodigo_paro (motivo_id, clave, nombre, nivel, clave_padre) VALUES\n" + ",\n".join(sub) + "\nON CONFLICT (motivo_id, clave) DO NOTHING;\n")

tp = sorted({v for v in R.TIPOS_PARO_MAQUINA.values() if v})
out.append("INSERT INTO oee.dim_tipo_paro_maquina (nombre, pierde_disponibilidad) VALUES\n" + ",\n".join(f"  ({q(n)}, {str(p).lower()})" for n, p in tp) + "\nON CONFLICT (nombre) DO NOTHING;\n")

out.append("""-- Calendario 2020-2030 (nombres de mes en español; no depende de lc_time del servidor)
INSERT INTO oee.dim_fecha (fecha, anio, trimestre, mes, nombre_mes, semana_iso, dia_semana, es_fin_semana)
SELECT d::date, EXTRACT(year FROM d), EXTRACT(quarter FROM d), EXTRACT(month FROM d),
       (ARRAY['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'])[EXTRACT(month FROM d)::int],
       EXTRACT(week FROM d), EXTRACT(isodow FROM d), EXTRACT(isodow FROM d) >= 6
FROM generate_series('2020-01-01'::date, '2030-12-31'::date, interval '1 day') AS d
ON CONFLICT (fecha) DO NOTHING;

COMMIT;""")
dest = Path(__file__).resolve().parent.parent / "sql" / "02_seed_catalogos.sql"
dest.write_text("\n".join(out) + "\n", encoding="utf-8")
print("escrito", dest)
