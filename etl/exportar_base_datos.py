#!/usr/bin/env python3
"""Genera la base de datos POBLADA a partir de las salidas del ETL (data/processed):
  1) base_datos_oee_postgres.sql : script único (esquema + catálogos + datos + lógica + vistas)
  2) base_datos_oee.sqlite       : copia navegable sin instalar servidor (tablas + vistas OEE)
Uso:  python exportar_base_datos.py <dir_processed> <dir_salida>
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import reglas as R

PROC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../data/processed")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".")
SQLDIR = Path(__file__).resolve().parent.parent / "sql"
PLAN = {m[0] for m in R.MOTIVOS if m[3]}


def q(v):
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
        return "NULL"
    if isinstance(v, (bool, np.bool_)):
        return "true" if v else "false"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return repr(round(float(v), 4))
    return "'" + str(v).replace("'", "''") + "'"


# ------------------------------------------------------------------ datos y llaves
reg = pd.read_csv(PROC / "registros_produccion.csv")
paros = pd.read_csv(PROC / "detalle_paros.csv")
rech = pd.read_csv(PROC / "rechazos_y_advertencias.csv")
metas = pd.read_csv(PROC / "metas_estimadas.csv")

maq_id = {n: i for i, n in enumerate(R.MAQUINAS, 1)}
turno_id = {t[0]: i for i, t in enumerate(R.TURNOS, 1)}
oper = sorted(reg.operario.dropna().unique())
oper_id = {n: i for i, n in enumerate(oper, 1)}
refs = sorted(reg.referencia.dropna().unique())
ref_id = {n: i for i, n in enumerate(refs, 1)}
tp_names = sorted({v[0] for v in R.TIPOS_PARO_MAQUINA.values() if v})
tp_id = {n: i for i, n in enumerate(tp_names, 1)}
sub_id, k = {}, 0                       # mismo orden de inserción que 02_seed_catalogos.sql
for cod, d in R.SUBCODIGOS.items():
    for clave in d:
        k += 1
        sub_id[(cod, clave)] = k

reg = reg.reset_index(drop=True)
reg["registro_id"] = reg.index + 1
paros = paros.merge(reg[["row_hash", "registro_id"]], on="row_hash", how="inner")
paros["plan"] = paros.motivo_id.isin(PLAN)
tot = paros.groupby("registro_id").apply(
    lambda g: pd.Series({"plan": g.loc[g.plan, "minutos"].sum(), "noplan": g.loc[~g.plan, "minutos"].sum()}),
    include_groups=False)
reg = reg.join(tot, on="registro_id").fillna({"plan": 0, "noplan": 0})
AREAS = {"Operarios", "Personal_de_mantenimiento"}

# ------------------------------------------------------------------ 1) PostgreSQL
L = ["-- =====================================================================================",
     "-- BASE DE DATOS OEE / PAROS DE PRODUCCIÓN (PostgreSQL 14+) — esquema + datos cargados",
     "-- Origen: SEGUIMIENTO_TEMPERAS_Y_VINILOS (2022-01-01 → 2025-03-28), procesado con etl_paros.py",
     "-- Uso:  createdb oee && psql -d oee -v ON_ERROR_STOP=1 -f base_datos_oee_postgres.sql",
     "-- Los datos se cargan ANTES de crear los triggers (los totales ya vienen calculados).",
     "-- =====================================================================================", ""]
L.append((SQLDIR / "01_ddl.sql").read_text(encoding="utf-8"))
L.append((SQLDIR / "02_seed_catalogos.sql").read_text(encoding="utf-8"))
L.append("BEGIN;")
L.append("INSERT INTO etl.lotes (lote_id, archivo, estado, finalizado_en, filas_leidas, filas_insertadas, mensaje) "
         "OVERRIDING SYSTEM VALUE VALUES (1, 'SEGUIMIENTO_TEMPERAS_Y_VINILOS_Actividad.xlsm', 'OK', now(), 8208, "
         f"{len(reg)}, 'Carga inicial desde el libro de Excel');")
L.append("INSERT INTO oee.dim_operario (operario_id, nombre) VALUES\n" +
         ",\n".join(f"  ({i}, {q(n)})" for n, i in oper_id.items()) + "\nON CONFLICT DO NOTHING;")
rows = []
for n, i in ref_id.items():
    marca, cc, col = R.parse_referencia(n)
    rows.append(f"  ({i}, {q(n)}, {q(marca)}, {q(cc)}, {q(col)})")
L.append("INSERT INTO oee.dim_referencia (referencia_id, nombre, marca, volumen_cc, num_colores) VALUES\n" +
         ",\n".join(rows) + "\nON CONFLICT DO NOTHING;")
L.append("SELECT setval(pg_get_serial_sequence('oee.dim_operario','operario_id'), (SELECT max(operario_id) FROM oee.dim_operario));")
L.append("SELECT setval(pg_get_serial_sequence('oee.dim_referencia','referencia_id'), (SELECT max(referencia_id) FROM oee.dim_referencia));")

mrows = []
for m in metas.itertuples():
    mrows.append(f"  ({maq_id[m.maquina]}, {ref_id.get(m.referencia, 0) if isinstance(m.referencia, str) else 0}, {m.meta_pacas_hora}, 'ESTIMADA_P90')")
L.append("INSERT INTO oee.meta_produccion (maquina_id, referencia_id, meta_pacas_hora, origen) VALUES\n" + ",\n".join(mrows) + "\nON CONFLICT DO NOTHING;")

cols = ("registro_id, row_hash, fecha, maquina_id, turno_id, operario_id, referencia_id, tipo_registro, pacas_producidas, "
        "horas_programadas, horas_no_programadas, tipo_paro_id, observacion, observacion_paro, calidad_dato, "
        "paro_planificado_min, paro_no_planificado_min, archivo_origen, fila_origen, lote_id")


def fila_reg(r):
    return (f"({r.registro_id}, {q(r.row_hash)}, {q(r.fecha)}, {maq_id[r.maquina]}, "
            f"{turno_id.get(r.turno, 0) if isinstance(r.turno, str) else 0}, "
            f"{oper_id.get(r.operario, 0) if isinstance(r.operario, str) else 0}, "
            f"{ref_id.get(r.referencia, 0) if isinstance(r.referencia, str) else 0}, {q(r.tipo_registro)}, {q(r.pacas)}, "
            f"{q(r.horas_programadas)}, {q(r.horas_no_programadas)}, "
            f"{tp_id[r.tipo_paro_maquina] if isinstance(r.tipo_paro_maquina, str) else 'NULL'}, {q(r.observacion)}, "
            f"{q(r.observacion_paro)}, {q(r.calidad_dato)}, {round(r.plan, 2)}, {round(r.noplan, 2)}, "
            f"{q(r.archivo_origen)}, {r.fila_origen}, 1)")


for i in range(0, len(reg), 500):
    L.append(f"INSERT INTO oee.registros_produccion ({cols}) OVERRIDING SYSTEM VALUE VALUES\n" +
             ",\n".join(fila_reg(r) for r in reg.iloc[i:i + 500].itertuples()) + ";")
L.append("SELECT setval(pg_get_serial_sequence('oee.registros_produccion','registro_id'), (SELECT max(registro_id) FROM oee.registros_produccion));")

maq_de_reg = dict(zip(reg.registro_id, reg.maquina.map(maq_id)))
pc = "registro_id, maquina_id, motivo_id, subcodigo_id, minutos, area_involucrada, personal_involucrado"


def fila_paro(p):
    sub = sub_id.get((p.motivo_id, p.subcodigo)) if isinstance(p.subcodigo, str) else None
    area = p.area_involucrada if p.area_involucrada in AREAS else None
    return (f"({p.registro_id}, {maq_de_reg[p.registro_id]}, {p.motivo_id}, {q(sub)}, {q(p.minutos)}, {q(area)}, "
            f"{q(p.personal_involucrado)})")


paros = paros.sort_values(["registro_id", "motivo_id"]).reset_index(drop=True)
for i in range(0, len(paros), 1000):
    L.append(f"INSERT INTO oee.detalle_paros_produccion ({pc}) VALUES\n" +
             ",\n".join(fila_paro(p) for p in paros.iloc[i:i + 1000].itertuples()) + ";")
L.append("INSERT INTO etl.rechazos (lote_id, fila_origen, regla, severidad, detalle) VALUES\n" +
         ",\n".join(f"  (1, {int(r.fila_origen)}, {q(r.regla)}, {q(r.severidad)}, {q(r.detalle)})" for r in rech.itertuples()) + ";")
L.append("COMMIT;\n")
L.append((SQLDIR / "03_logica_negocio.sql").read_text(encoding="utf-8"))
L.append((SQLDIR / "04_vistas_oee.sql").read_text(encoding="utf-8"))
L.append("\n-- Verificación rápida\nSELECT 'registros' AS tabla, count(*) FROM oee.registros_produccion\n"
         "UNION ALL SELECT 'detalle_paros', count(*) FROM oee.detalle_paros_produccion\n"
         "UNION ALL SELECT 'rechazos', count(*) FROM etl.rechazos;\nSELECT * FROM oee.v_oee_mensual ORDER BY mes, maquina LIMIT 12;")
(OUT / "base_datos_oee_postgres.sql").write_text("\n".join(L), encoding="utf-8")

# ------------------------------------------------------------------ 2) SQLite
db = OUT / "base_datos_oee.sqlite"
db.unlink(missing_ok=True)
c = sqlite3.connect(db)
c.executescript("""
PRAGMA foreign_keys=ON;
CREATE TABLE dim_maquina(maquina_id INTEGER PRIMARY KEY, nombre TEXT UNIQUE, linea TEXT);
CREATE TABLE dim_turno(turno_id INTEGER PRIMARY KEY, nombre TEXT, hora_inicio TEXT, hora_fin TEXT, horas_nominales REAL);
CREATE TABLE dim_operario(operario_id INTEGER PRIMARY KEY, nombre TEXT UNIQUE);
CREATE TABLE dim_referencia(referencia_id INTEGER PRIMARY KEY, nombre TEXT UNIQUE, marca TEXT, volumen_cc INTEGER, num_colores INTEGER);
CREATE TABLE dim_area_impacto(area_id INTEGER PRIMARY KEY, nombre TEXT UNIQUE);
CREATE TABLE dim_motivo_paro(motivo_id INTEGER PRIMARY KEY, nombre TEXT, area_id INTEGER REFERENCES dim_area_impacto, es_planificado INTEGER, categoria_oee TEXT);
CREATE TABLE dim_subcodigo_paro(subcodigo_id INTEGER PRIMARY KEY, motivo_id INTEGER REFERENCES dim_motivo_paro, clave TEXT, nombre TEXT, nivel INTEGER, clave_padre TEXT);
CREATE TABLE dim_tipo_paro_maquina(tipo_paro_id INTEGER PRIMARY KEY, nombre TEXT UNIQUE, pierde_disponibilidad INTEGER);
CREATE TABLE meta_produccion(maquina_id INTEGER REFERENCES dim_maquina, referencia_id INTEGER REFERENCES dim_referencia, meta_pacas_hora REAL, origen TEXT, PRIMARY KEY(maquina_id, referencia_id));
CREATE TABLE registros_produccion(registro_id INTEGER PRIMARY KEY, row_hash TEXT UNIQUE, fecha TEXT NOT NULL,
  maquina_id INTEGER REFERENCES dim_maquina, turno_id INTEGER REFERENCES dim_turno, operario_id INTEGER REFERENCES dim_operario,
  referencia_id INTEGER REFERENCES dim_referencia, tipo_registro TEXT, pacas_producidas REAL, pacas_no_conformes REAL DEFAULT 0,
  horas_programadas REAL, horas_no_programadas REAL, tipo_paro_id INTEGER REFERENCES dim_tipo_paro_maquina, observacion TEXT,
  observacion_paro TEXT, calidad_dato TEXT, paro_planificado_min REAL, paro_no_planificado_min REAL, archivo_origen TEXT, fila_origen INTEGER);
CREATE TABLE detalle_paros_produccion(detalle_id INTEGER PRIMARY KEY AUTOINCREMENT, registro_id INTEGER REFERENCES registros_produccion,
  maquina_id INTEGER REFERENCES dim_maquina, motivo_id INTEGER REFERENCES dim_motivo_paro, subcodigo_id INTEGER REFERENCES dim_subcodigo_paro,
  minutos REAL, area_involucrada TEXT, personal_involucrado TEXT);
CREATE TABLE rechazos(rechazo_id INTEGER PRIMARY KEY AUTOINCREMENT, fila_origen INTEGER, regla TEXT, severidad TEXT, detalle TEXT);
CREATE INDEX ix_reg_fecha ON registros_produccion(fecha, maquina_id);
CREATE INDEX ix_det_reg ON detalle_paros_produccion(registro_id);
""")
c.executemany("INSERT INTO dim_maquina VALUES (?,?,?)", [(i, n, "Vinilos y témperas") for n, i in maq_id.items()])
c.execute("INSERT INTO dim_turno VALUES (0,'Sin dato',NULL,NULL,NULL)")
c.executemany("INSERT INTO dim_turno VALUES (?,?,?,?,?)", [(i, *t) for i, t in enumerate(R.TURNOS, 1)])
c.execute("INSERT INTO dim_operario VALUES (0,'Sin dato')")
c.executemany("INSERT INTO dim_operario VALUES (?,?)", [(i, n) for n, i in oper_id.items()])
c.execute("INSERT INTO dim_referencia VALUES (0,'Sin dato',NULL,NULL,NULL)")
c.executemany("INSERT INTO dim_referencia VALUES (?,?,?,?,?)", [(i, n, *R.parse_referencia(n)) for n, i in ref_id.items()])
areas = sorted({m[2] for m in R.MOTIVOS})
c.executemany("INSERT INTO dim_area_impacto VALUES (?,?)", [(i, a) for i, a in enumerate(areas, 1)])
c.executemany("INSERT INTO dim_motivo_paro VALUES (?,?,?,?,?)", [(m[0], m[1], areas.index(m[2]) + 1, int(m[3]), m[4]) for m in R.MOTIVOS])
srows = []
for cod, d in R.SUBCODIGOS.items():
    for clave, nom in d.items():
        nivel = 1 if (cod != 1 or clave.count(".") == 1) else 2
        srows.append((sub_id[(cod, clave)], cod, clave, nom, nivel, ".".join(clave.split(".")[:2]) if (cod == 1 and nivel == 2) else None))
c.executemany("INSERT INTO dim_subcodigo_paro VALUES (?,?,?,?,?,?)", srows)
pd_ = {v[0]: int(v[1]) for v in R.TIPOS_PARO_MAQUINA.values() if v}
c.executemany("INSERT INTO dim_tipo_paro_maquina VALUES (?,?,?)", [(i, n, pd_[n]) for n, i in tp_id.items()])
c.executemany("INSERT INTO meta_produccion VALUES (?,?,?,?)",
              [(maq_id[m.maquina], ref_id.get(m.referencia, 0) if isinstance(m.referencia, str) else 0, m.meta_pacas_hora, "ESTIMADA_P90") for m in metas.itertuples()])


def nn(v):
    return None if (v is None or (isinstance(v, float) and np.isnan(v))) else (v.item() if hasattr(v, "item") else v)


c.executemany("INSERT INTO registros_produccion VALUES (?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?,?,?)", [
    (int(r.registro_id), r.row_hash, r.fecha, maq_id[r.maquina], turno_id.get(r.turno, 0) if isinstance(r.turno, str) else 0,
     oper_id.get(r.operario, 0) if isinstance(r.operario, str) else 0, ref_id.get(r.referencia, 0) if isinstance(r.referencia, str) else 0,
     r.tipo_registro, nn(r.pacas), r.horas_programadas, r.horas_no_programadas,
     tp_id[r.tipo_paro_maquina] if isinstance(r.tipo_paro_maquina, str) else None, nn(r.observacion), nn(r.observacion_paro),
     r.calidad_dato, float(r.plan), float(r.noplan), r.archivo_origen, int(r.fila_origen)) for r in reg.itertuples()])
c.executemany("INSERT INTO detalle_paros_produccion(registro_id,maquina_id,motivo_id,subcodigo_id,minutos,area_involucrada,personal_involucrado) VALUES (?,?,?,?,?,?,?)", [
    (int(p.registro_id), maq_de_reg[p.registro_id], int(p.motivo_id),
     sub_id.get((p.motivo_id, p.subcodigo)) if isinstance(p.subcodigo, str) else None, float(p.minutos),
     p.area_involucrada if p.area_involucrada in AREAS else None, nn(p.personal_involucrado)) for p in paros.itertuples()])
c.executemany("INSERT INTO rechazos(fila_origen,regla,severidad,detalle) VALUES (?,?,?,?)",
              [(int(r.fila_origen), r.regla, r.severidad, r.detalle) for r in rech.itertuples()])
c.executescript("""
CREATE VIEW v_oee_turno AS
WITH base AS (
  SELECT r.*, MAX(tipo_registro='PRODUCCION') OVER (PARTITION BY fecha, maquina_id, turno_id, operario_id, referencia_id) AS en_alcance,
         COALESCE((SELECT meta_pacas_hora FROM meta_produccion m WHERE m.maquina_id=r.maquina_id AND m.referencia_id=r.referencia_id),
                  (SELECT meta_pacas_hora FROM meta_produccion m WHERE m.maquina_id=r.maquina_id AND m.referencia_id=0)) AS meta
  FROM registros_produccion r WHERE calidad_dato<>'POSIBLE_DUPLICADO'),
g AS (SELECT fecha, maquina_id, turno_id, operario_id, referencia_id, MAX(meta) AS meta, SUM(horas_programadas*60) AS prog,
        SUM(paro_planificado_min) AS plan, SUM(paro_no_planificado_min) AS noplan_b, SUM(COALESCE(pacas_producidas,0)) AS pacas,
        SUM(COALESCE(pacas_producidas,0)-pacas_no_conformes) AS buenas
      FROM base WHERE en_alcance=1 GROUP BY fecha, maquina_id, turno_id, operario_id, referencia_id),
c AS (SELECT *, MAX(prog-plan,0) AS planificado FROM g)
SELECT fecha, maquina_id, turno_id, operario_id, referencia_id, prog AS min_programados, plan AS min_paro_planificado, planificado AS min_planificados,
  MIN(noplan_b, planificado) AS min_paro_no_planificado, planificado-MIN(noplan_b, planificado) AS min_operativos,
  pacas AS pacas_producidas, buenas AS pacas_buenas, meta AS meta_pacas_hora,
  (planificado-MIN(noplan_b, planificado))/60.0*meta AS pacas_ideales_operativas, planificado/60.0*meta AS pacas_ideales_planificadas
FROM c;
CREATE VIEW v_oee_mensual AS
SELECT substr(t.fecha,1,7) AS mes, m.nombre AS maquina,
  ROUND(SUM(min_operativos)*1.0/NULLIF(SUM(min_planificados),0),4) AS disponibilidad,
  ROUND(SUM(pacas_producidas)/NULLIF(SUM(pacas_ideales_operativas),0),4) AS rendimiento,
  ROUND(SUM(pacas_buenas)/NULLIF(SUM(pacas_producidas),0),4) AS calidad,
  ROUND(SUM(pacas_buenas)/NULLIF(SUM(pacas_ideales_planificadas),0),4) AS oee
FROM v_oee_turno t JOIN dim_maquina m USING(maquina_id) GROUP BY 1,2;
CREATE VIEW v_paros_detalle AS
SELECT d.detalle_id, r.fecha, ma.nombre AS maquina, mo.motivo_id, mo.nombre AS motivo, mo.es_planificado,
  COALESCE(sc.nombre,'Sin especificar') AS subcodigo, d.minutos, d.minutos/60.0 AS horas
FROM detalle_paros_produccion d JOIN registros_produccion r USING(registro_id) JOIN dim_maquina ma ON ma.maquina_id=r.maquina_id
JOIN dim_motivo_paro mo ON mo.motivo_id=d.motivo_id LEFT JOIN dim_subcodigo_paro sc ON sc.subcodigo_id=d.subcodigo_id
WHERE r.calidad_dato<>'POSIBLE_DUPLICADO';
""")
c.commit()
for t in ["registros_produccion", "detalle_paros_produccion", "rechazos", "dim_operario", "dim_referencia"]:
    print(t, c.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
print("FK check:", c.execute("PRAGMA foreign_key_check").fetchall()[:3])
print(c.execute("SELECT substr(fecha,1,4) a, ROUND(SUM(pacas_buenas)/SUM(pacas_ideales_planificadas),4) FROM v_oee_turno GROUP BY 1").fetchall())
c.close()
print("ok")
