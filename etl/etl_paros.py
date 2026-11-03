#!/usr/bin/env python3
"""
ETL incremental de registros de producción y paros (libro SEGUIMIENTO_TEMPERAS_Y_VINILOS.xlsm)
hacia PostgreSQL.

Flujo (idempotente):
  1. EXTRAE  la hoja 'Base De Datos' (encabezado en la fila 9).
  2. TRANSFORMA: normaliza textos, re-mapea subcódigos legados, des-pivotea los 18 códigos de paro
     (columnas "Codigo de paro N", en MINUTOS) a filas de detalle.
  3. VALIDA con reglas de negocio; lo inválido va a rechazos (etl.rechazos) con su regla.
  4. CARGA a stg.* y delega en el procedimiento almacenado etl.sp_promover_lote(), que hace el
     upsert transaccional por hash de fila (sin duplicados) y registra el lote en etl.lotes.

Modos:
  --dry-run   no toca la BD; escribe CSV/JSON en --salida (sirve para auditar y para pruebas).
  (sin flag)  carga real; requiere psycopg2 y la variable DATABASE_URL.

Uso:
  python etl_paros.py --archivo ../data/raw/SEGUIMIENTO.xlsm --dry-run --salida ../data/processed
  DATABASE_URL=postgresql://user:pass@host:5432/oee python etl_paros.py --archivo X.xlsm
  python etl_paros.py --archivo X.xlsm --reemplazar-desde 2025-03-01   # re-sincroniza correcciones
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import reglas as R  

log = logging.getLogger("etl_paros")

HOJA = "Base De Datos"
FILA_ENCABEZADO = 8                  
PRIMERA_FILA_DATOS_EXCEL = 10
N_CODIGOS = 18
TOLERANCIA_MIN = 5                   
MAX_PACAS_HORA = 400                 

COL = {
    "fecha": "Fecha", "maquina": "Maquina", "operario": "Operario", "referencia": "Referencia",
    "pacas": "Pacas producidas", "horas": "Horas trabajadas", "turno": "Turno",
    "horas_no": "Horas no trabajadas", "tipo_paro": "Tipo de paro",
    "obs_paro": "Observaciones de paro", "obs": "Observaciones",
    "sub1": "Sub Codigo de paro 1", "sub3": "Subcodigo 3", "sub5": "Subcodigo 5",
    "area5": "Área involucrada en subcodigo 5", "personal5": "Personal involucrado",
}



def extraer(archivo: Path) -> pd.DataFrame:
    df = pd.read_excel(archivo, sheet_name=HOJA, header=FILA_ENCABEZADO, engine="openpyxl")
    df.columns = [str(c).replace("\n", " ").strip() for c in df.columns]
   
    df = df.rename(columns={c: c for c in df.columns})
    df["fila_origen"] = np.arange(len(df)) + PRIMERA_FILA_DATOS_EXCEL
    return df



def _txt(v):
    return R.norm_texto(None if (v is None or (isinstance(v, float) and np.isnan(v))) else v)


def _hash_fila(partes: list, seq: int) -> str:
    base = "|".join("" if p is None else str(p) for p in partes) + f"#{seq}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def transformar(df: pd.DataFrame, archivo: str):
    """Devuelve (registros, paros, rechazos) como DataFrames."""
    reg_rows, paro_rows, rech = [], [], []
    vistos: dict[str, int] = {}
    hoy = pd.Timestamp(date.today())
    vacias = 0

    for _, r in df.iterrows():
        fila = int(r["fila_origen"])

        def rechazar(regla, sev, detalle):
            rech.append(dict(fila_origen=fila, regla=regla, severidad=sev, detalle=detalle))

        fecha = pd.to_datetime(r.get(COL["fecha"]), errors="coerce")
        maquina = _txt(r.get(COL["maquina"]))
        minutos = {n: r.get(f"Codigo de paro {n}") for n in range(1, N_CODIGOS + 1)}
        minutos = {n: (0.0 if pd.isna(v) else float(v)) for n, v in minutos.items()}
        pacas = r.get(COL["pacas"])
        pacas = None if pd.isna(pacas) else float(pacas)
        horas = r.get(COL["horas"])
        horas = None if pd.isna(horas) else float(horas)
        horas_no = r.get(COL["horas_no"])
        horas_no = None if pd.isna(horas_no) else float(horas_no)

        
        if pd.isna(fecha) and maquina is None:
            vacias += 1
            continue
        if not horas and not pacas and not any(minutos.values()) and not horas_no:
            vacias += 1
            continue

       
        if pd.isna(fecha) or fecha > hoy or fecha.year < 2020:
            rechazar("R01_FECHA_INVALIDA", "ERROR", f"fecha={r.get(COL['fecha'])}")
            continue
        if maquina not in R.MAQUINAS:
            rechazar("R02_MAQUINA_DESCONOCIDA", "ERROR", f"maquina={maquina}")
            continue
        if any(v < 0 for v in minutos.values()) or (horas is not None and horas < 0) \
                or (pacas is not None and pacas < 0) or (horas_no is not None and horas_no < 0):
            rechazar("R03_VALOR_NEGATIVO", "ERROR", "minutos/horas/pacas negativos")
            continue
        if horas and pacas and horas > 24:
            rechazar("R04_HORAS_FUERA_DE_RANGO", "ERROR", f"horas={horas}")
            continue
        total_min = sum(minutos.values())
        planif_min = sum(minutos[m[0]] for m in R.MOTIVOS if m[3])
        oper_h = ((horas or 0) * 60 - total_min) / 60
        if pacas and horas and pacas / max(horas - planif_min / 60, 1) > MAX_PACAS_HORA:
            rechazar("R05_PACAS_FUERA_DE_RANGO", "ERROR",
                     f"{pacas:.0f} 'pacas' en {horas}h (probable unidad distinta, p.ej. unidades sueltas)")
            continue

        turno = _txt(r.get(COL["turno"]))
        operario = _txt(r.get(COL["operario"]))
        referencia = _txt(r.get(COL["referencia"]))
        turno = None if turno == R.SIN_DATO else turno
        operario = None if operario in (R.SIN_DATO, "No") else operario
        referencia = None if referencia == R.SIN_DATO else referencia

        tp_clave = R.clave_tipo_paro(r.get(COL["tipo_paro"]))
        tp = R.TIPOS_PARO_MAQUINA.get(tp_clave) if tp_clave else None
        if tp_clave and tp_clave not in R.TIPOS_PARO_MAQUINA:
            tp = (_txt(r.get(COL["tipo_paro"])), True)
            rechazar("R08_TIPO_PARO_NO_CATALOGADO", "WARNING", f"tipo_paro={tp[0]}")

        calidad = "OK"
        if horas and total_min > horas * 60 + TOLERANCIA_MIN:
            calidad = "REVISAR"
            rechazar("R06_PAROS_EXCEDEN_TURNO", "WARNING",
                     f"paros={total_min:.0f} min > turno={horas * 60:.0f} min (se carga marcado REVISAR)")
        tipo_registro = "PRODUCCION" if (horas or pacas) else "COMPLEMENTO_PAROS"

        
        partes = [fecha.date(), maquina, turno, operario, referencia, pacas, horas, horas_no,
                  tp[0] if tp else None, *[minutos[n] for n in range(1, N_CODIGOS + 1)],
                  _txt(r.get(COL["sub1"])), _txt(r.get(COL["sub3"])), _txt(r.get(COL["sub5"]))]
        base = _hash_fila(partes, 0)
        seq = vistos.get(base, 0)
        vistos[base] = seq + 1
        row_hash = _hash_fila(partes, seq)
        if seq > 0:
            calidad = "POSIBLE_DUPLICADO"
            rechazar("R07_POSIBLE_DUPLICADO", "WARNING", f"contenido idéntico repetido (copia #{seq + 1})")

        reg_rows.append(dict(
            row_hash=row_hash, fila_origen=fila, archivo_origen=archivo, fecha=fecha.date(),
            maquina=maquina, turno=turno, operario=operario, referencia=referencia,
            pacas=pacas, horas_programadas=horas or 0.0, horas_no_programadas=horas_no or 0.0,
            tipo_paro_maquina=tp[0] if tp else None, pierde_disp_tpm=tp[1] if tp else None,
            observacion=_txt(r.get(COL["obs"])), observacion_paro=_txt(r.get(COL["obs_paro"])),
            tipo_registro=tipo_registro, calidad_dato=calidad))

       
        for n, mins in minutos.items():
            if mins <= 0:
                continue
            sub_txt = {1: r.get(COL["sub1"]), 3: r.get(COL["sub3"]), 5: r.get(COL["sub5"])}.get(n)
            sub = R.normaliza_subcodigo(n, sub_txt) if n in (1, 3, 5) else None
            if n in (1, 3, 5) and _txt(sub_txt) and sub is None \
                    and R.sin_acentos(_txt(sub_txt)).lower() != "sin especificar":
                rechazar("R09_SUBCODIGO_NO_RECONOCIDO", "WARNING", f"codigo={n} sub='{_txt(sub_txt)}'")
            paro_rows.append(dict(
                row_hash=row_hash, motivo_id=n, minutos=mins, subcodigo=sub,
                area_involucrada=_txt(r.get(COL["area5"])) if n == 5 else None,
                personal_involucrado=_txt(r.get(COL["personal5"])) if n == 5 else None))

    reg = pd.DataFrame(reg_rows)
    paros = pd.DataFrame(paro_rows)
    rechazos = pd.DataFrame(rech, columns=["fila_origen", "regla", "severidad", "detalle"])
    log.info("filas vacías omitidas: %d", vacias)
    reg.attrs["vacias"] = vacias
    return reg, paros, rechazos



def estimar_metas(reg: pd.DataFrame, paros: pd.DataFrame, p: float = 0.90, min_n: int = 10) -> pd.DataFrame:
    """Meta de pacas/hora = percentil 90 del ritmo observado en tiempo operativo (mejor ritmo
    demostrado). Es un SUSTITUTO documentado de la meta oficial (columna 'Meta por hora' del
    formulario hora a hora, que no se almacena en el libro). Se reemplaza cargando metas con
    origen='OFICIAL' en oee.meta_produccion."""
    planif = {m[0] for m in R.MOTIVOS if m[3]}
    pm = paros.assign(planif=paros.motivo_id.isin(planif))
    agg = pm.groupby("row_hash").apply(
        lambda g: pd.Series({"min_plan": g.loc[g.planif, "minutos"].sum(),
                             "min_noplan": g.loc[~g.planif, "minutos"].sum()}), include_groups=False)
    d = reg[(reg.tipo_registro == "PRODUCCION") & (reg.pacas > 0) & (reg.horas_programadas > 0)
            & (reg.calidad_dato != "POSIBLE_DUPLICADO")].join(agg, on="row_hash").fillna({"min_plan": 0, "min_noplan": 0})
    d["h_oper"] = d.horas_programadas - (d.min_plan + d.min_noplan) / 60
    d = d[d.h_oper >= 1]
    d["ritmo"] = d.pacas / d.h_oper
    out = []
    for maq, g in d.groupby("maquina"):
        out.append(dict(maquina=maq, referencia=None, meta_pacas_hora=round(g.ritmo.quantile(p), 2), n=len(g)))
        for ref, gr in g.dropna(subset=["referencia"]).groupby("referencia"):
            if len(gr) >= min_n:
                out.append(dict(maquina=maq, referencia=ref, meta_pacas_hora=round(gr.ritmo.quantile(p), 2), n=len(gr)))
    return pd.DataFrame(out)



def _py(v):
    """numpy/pandas -> tipos nativos de Python (psycopg2 no adapta numpy.int64) y NaN -> None."""
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    return v.item() if hasattr(v, "item") else v


def cargar_a_postgres(reg, paros, rechazos, metas, archivo: Path, reemplazar_desde: str | None):
    try:
        import psycopg2
        from psycopg2.extras import execute_values
    except ImportError:
        sys.exit("Falta psycopg2: pip install psycopg2-binary (o use --dry-run)")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("Defina DATABASE_URL, p.ej. postgresql://usuario:clave@host:5432/oee")

    sha = hashlib.sha256(archivo.read_bytes()).hexdigest()
    conn = psycopg2.connect(dsn)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT etl.fn_iniciar_lote(%s, %s, %s)", (archivo.name, sha, len(reg)))
            lote = cur.fetchone()[0]
            if lote is None:
                log.warning("Archivo ya procesado (mismo SHA-256) y sin cambios: nada que hacer.")
                return
            cols = ["row_hash", "fila_origen", "archivo_origen", "fecha", "maquina", "turno", "operario",
                    "referencia", "pacas", "horas_programadas", "horas_no_programadas", "tipo_paro_maquina",
                    "pierde_disp_tpm", "observacion", "observacion_paro", "tipo_registro", "calidad_dato"]
            execute_values(cur, f"INSERT INTO stg.registros (lote_id,{','.join(cols)}) VALUES %s",
                           [(lote, *[_py(v) for v in row]) for row in reg[cols].itertuples(index=False)],
                           page_size=2000)
            pc = ["row_hash", "motivo_id", "minutos", "subcodigo", "area_involucrada", "personal_involucrado"]
            if len(paros):
                execute_values(cur, f"INSERT INTO stg.paros (lote_id,{','.join(pc)}) VALUES %s",
                               [(lote, *[_py(v) for v in row]) for row in paros[pc].itertuples(index=False)],
                               page_size=5000)
            if len(rechazos):
                execute_values(cur, "INSERT INTO etl.rechazos (lote_id,fila_origen,regla,severidad,detalle) VALUES %s",
                               [(lote, _py(a), b, c, d) for a, b, c, d in rechazos.itertuples(index=False)], page_size=2000)
            cur.execute("CALL etl.sp_promover_lote(%s, %s)", (lote, reemplazar_desde))
            if len(metas):
                cur.executemany("SELECT etl.fn_upsert_meta_estimada(%s, %s, %s)",
                                [(m.maquina, _py(m.referencia), float(m.meta_pacas_hora)) for m in metas.itertuples()])
            log.info("Lote %s cargado.", lote)
    except Exception as exc:                                    

        conn.rollback()
        with conn, conn.cursor() as cur:
            cur.execute("SELECT etl.fn_registrar_error(%s, %s)", (archivo.name, str(exc)[:2000]))
        raise
    finally:
        conn.close()



def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archivo", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--salida", type=Path, default=Path("../data/processed"))
    ap.add_argument("--reemplazar-desde", help="YYYY-MM-DD: borra y recarga lo del archivo desde esa fecha")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    df = extraer(a.archivo)
    reg, paros, rechazos = transformar(df, a.archivo.name)
    metas = estimar_metas(reg, paros)

    resumen = {
        "filas_leidas": int(len(df)), "filas_vacias_omitidas": int(reg.attrs.get("vacias", 0)),
        "registros_validos": int(len(reg)), "detalles_de_paro": int(len(paros)),
        "rechazos_ERROR": int((rechazos.severidad == "ERROR").sum()),
        "advertencias": int((rechazos.severidad == "WARNING").sum()),
        "por_regla": rechazos.groupby("regla").size().to_dict(),
        "calidad_dato": reg.calidad_dato.value_counts().to_dict(),
        "tipo_registro": reg.tipo_registro.value_counts().to_dict(),
        "rango_fechas": [str(reg.fecha.min()), str(reg.fecha.max())],
        "metas_estimadas": int(len(metas)),
    }
    log.info(json.dumps(resumen, ensure_ascii=False, indent=2))

    if a.dry_run:
        a.salida.mkdir(parents=True, exist_ok=True)
        reg.to_csv(a.salida / "registros_produccion.csv", index=False)
        paros.to_csv(a.salida / "detalle_paros.csv", index=False)
        rechazos.to_csv(a.salida / "rechazos_y_advertencias.csv", index=False)
        metas.to_csv(a.salida / "metas_estimadas.csv", index=False)
        (a.salida / "resumen_etl.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2))
        log.info("Dry-run: archivos escritos en %s", a.salida)
    else:
        cargar_a_postgres(reg, paros, rechazos, metas, a.archivo, a.reemplazar_desde)


if __name__ == "__main__":
    main()
