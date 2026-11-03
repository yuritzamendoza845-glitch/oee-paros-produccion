#!/usr/bin/env python3
"""Incrusta los CSV de datos/ dentro de las consultas del modelo (OEE.SemanticModel), comprimidos en
Base64, para que el proyecto abra en cualquier PC SIN parametros ni rutas.
Ejecutar despues de generar_datos.py:   python generar_datos.py && python incrustar_datos.py"""
import csv, json, zlib, base64, re, glob, os
aqui = os.path.dirname(os.path.abspath(__file__))
T = "\t"
for tmdl in sorted(glob.glob(os.path.join(aqui, "OEE.SemanticModel", "definition", "tables", "*.tmdl"))):
    nombre = os.path.basename(tmdl)[:-5]
    if nombre == "_Medidas":
        continue
    with open(os.path.join(aqui, "datos", nombre + ".csv"), encoding="utf-8", newline="") as f:
        filas = list(csv.reader(f))
    cols, datos = filas[0], [[c if c != "" else None for c in r] for r in filas[1:]]
    crudo = json.dumps(datos, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    co = zlib.compressobj(9, zlib.DEFLATED, -15)          # DEFLATE crudo = Compression.Deflate de Power Query
    b64 = base64.b64encode(co.compress(crudo) + co.flush()).decode()
    trozos = [b64[i:i + 8000] for i in range(0, len(b64), 8000)]
    nombres = ", ".join('"%s"' % c for c in cols)
    nuevo = (f"{T*5}Datos = Text.Combine({{\n" + ",\n".join(f'{T*6}"{t}"' for t in trozos) + "}),\n"
             f"{T*5}Fuente = Json.Document(Binary.Decompress(Binary.FromText(Datos, BinaryEncoding.Base64), Compression.Deflate)),\n"
             f"{T*5}Encabezados = Table.FromRows(Fuente, {{{nombres}}}),\n")
    s = open(tmdl, encoding="utf-8").read()
    s2, n = re.subn(r"(\t+let\n).*?(\t+Tipos = )", lambda m: m.group(1) + nuevo + m.group(2), s, count=1, flags=re.S)
    assert n == 1, nombre
    open(tmdl, "w", encoding="utf-8", newline="\n").write(s2)
    print(f"{nombre}: {len(datos)} filas, {len(b64)//1024} KB incrustados")
