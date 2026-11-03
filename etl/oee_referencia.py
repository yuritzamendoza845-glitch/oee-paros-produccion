#!/usr/bin/env python3
"""Implementación de REFERENCIA (pandas) de las vistas oee.v_oee_turno / v_oee_diario / v_oee_mensual.
Sirve para conciliar los números de PostgreSQL contra una segunda implementación independiente:
    python oee_referencia.py ../data/processed  ->  oee_mensual_referencia.csv, oee_diario_referencia.csv
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import reglas as R

PLAN = {m[0] for m in R.MOTIVOS if m[3]}


def calcular(dir_: Path):
    r = pd.read_csv(dir_ / "registros_produccion.csv", parse_dates=["fecha"])
    p = pd.read_csv(dir_ / "detalle_paros.csv")
    metas = pd.read_csv(dir_ / "metas_estimadas.csv")
    r = r[r.calidad_dato != "POSIBLE_DUPLICADO"].copy()
    pp = p.assign(plan=p.motivo_id.isin(PLAN))
    s = pp.groupby("row_hash").apply(lambda g: pd.Series({
        "plan": g.loc[g.plan, "minutos"].sum(), "noplan": g.loc[~g.plan, "minutos"].sum()}), include_groups=False)
    r = r.join(s, on="row_hash").fillna({"plan": 0, "noplan": 0})
    k = ["fecha", "maquina", "turno", "operario", "referencia"]
    kk = r[k].fillna("~")
    r["_k"] = kk.astype(str).agg("|".join, axis=1)
    r["alcance"] = r.groupby("_k").tipo_registro.transform(lambda x: (x == "PRODUCCION").any())
    r = r[r.alcance].copy()
    m0 = metas[metas.referencia.isna()].set_index("maquina").meta_pacas_hora
    m1 = metas.dropna(subset=["referencia"]).set_index(["maquina", "referencia"]).meta_pacas_hora
    r["meta"] = [m1.get((a, b), m0.get(a, np.nan)) for a, b in zip(r.maquina, r.referencia)]
    r["prog"] = r.horas_programadas * 60
    r["pacas"] = r.pacas.fillna(0)
    r["no_prog_h"] = np.where(r.tipo_registro == "PRODUCCION", r.horas_no_programadas, 0)
    g = r.groupby("_k").agg(fecha=("fecha", "first"), maquina=("maquina", "first"), meta=("meta", "max"),
                            prog=("prog", "sum"), plan=("plan", "sum"), noplan=("noplan", "sum"), pacas=("pacas", "sum"))
    g["planificado"] = (g.prog - g.plan).clip(lower=0)
    g["noplan"] = np.minimum(g.noplan, g.planificado)
    g["operativo"] = g.planificado - g.noplan
    g["ideal_op"] = g.operativo / 60 * g.meta
    g["ideal_plan"] = g.planificado / 60 * g.meta
    g["buenas"] = g.pacas            # sin dato de no conformes => Q = 100 %
    return g


def indicadores(df, by):
    a = df.groupby(by).agg(planificado=("planificado", "sum"), operativo=("operativo", "sum"), pacas=("pacas", "sum"),
                           ideal_op=("ideal_op", "sum"), ideal_plan=("ideal_plan", "sum"), buenas=("buenas", "sum"))
    a["disponibilidad"] = a.operativo / a.planificado
    a["rendimiento"] = a.pacas / a.ideal_op
    a["calidad"] = a.buenas / a.pacas
    a["oee"] = a.buenas / a.ideal_plan
    return a.round(4)


if __name__ == "__main__":
    d = Path(sys.argv[1] if len(sys.argv) > 1 else "../data/processed")
    g = calcular(d)
    g["mes"] = g.fecha.dt.to_period("M").astype(str)
    indicadores(g, ["mes", "maquina"]).to_csv(d / "oee_mensual_referencia.csv")
    indicadores(g, ["maquina"]).to_csv(d / "oee_por_maquina_referencia.csv")
    indicadores(g.assign(anio=g.fecha.dt.year), ["anio"]).to_csv(d / "oee_anual_referencia.csv")
    print(indicadores(g, ["maquina"]).to_string()); print(indicadores(g.assign(anio=g.fecha.dt.year), ["anio"]).to_string())
