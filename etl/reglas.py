"""Catálogos y reglas de normalización compartidas por el ETL y el generador de semillas.

Fuente: hoja 'TABLA CODIGOS' del libro SEGUIMIENTO_TEMPERAS_Y_VINILOS y procedimiento P-MTO-22.
"""
import re
import unicodedata

# --- Códigos de paro (P-MTO-22 + TABLA CODIGOS: área de impacto / paro programado) ---------------
# (id, nombre, area, es_planificado, categoria_oee)
MOTIVOS = [
    (1,  "Falla del sistema electromecánico y/o de control",           "Mantenimiento",              False, "AVERIA"),
    (2,  "Espera de soporte de mantenimiento",                         "Mantenimiento",              False, "ESPERA"),
    (3,  "Novedad en los sistemas de potencia (aire, energía, vapor)", "Mantenimiento",              False, "AVERIA"),
    (4,  "Mantenimiento preventivo",                                   "Mantenimiento",              False, "AVERIA"),
    (5,  "Ajuste operativo",                                           "Producción",                 False, "AJUSTE"),
    (6,  "Limpieza por derrame operativo / tiempo sin reportar",       "Producción",                 False, "AJUSTE"),
    (7,  "Alistamiento de máquina / cambio de referencia",             "Producción",                 False, "CAMBIO_REFERENCIA"),
    (8,  "Capacitación / reunión",                                     "Producción",                 False, "ORGANIZACIONAL"),
    (9,  "Falta de operario",                                          "Producción",                 False, "ORGANIZACIONAL"),
    (10, "Paro por ventaja / evacuación / calidad",                    "Producción",                 False, "AJUSTE"),
    (11, "Reproceso",                                                  "Producción",                 False, "CALIDAD"),
    (12, "Materia prima defectuosa",                                   "Calidad",                    False, "CALIDAD"),
    (13, "En espera por el aval del laboratorio de microbiología",     "Calidad",                    False, "ESPERA"),
    (14, "Falta de materia prima",                                     "Almacén de materias primas", False, "ABASTECIMIENTO"),
    (15, "Cambio de insumos (roscadores, o'ring, etiquetas)",          "Paro programado",            True,  "PLANIFICADO"),
    (16, "Alimentación y aseo de la zona de trabajo y la máquina",     "Paro programado",            True,  "PLANIFICADO"),
    (17, "Pausa activa",                                               "Paro programado",            True,  "PLANIFICADO"),
    (18, "Desinfección",                                               "Paro programado",            True,  "PLANIFICADO"),
]
# Nota: el 18 (Desinfección) no está en TABLA CODIGOS pero sí en el formulario 'Registro' y en la
# base de datos (8 filas). Se clasifica como planificado por ser rutina sanitaria; es configurable
# en oee.dim_motivo_paro.es_planificado.

TURNOS = [
    # nombre, inicio, fin, horas nominales
    ("6am-2pm (Turno 1)",  "06:00", "14:00", 8.0),
    ("2pm-10pm (Turno 2)", "14:00", "22:00", 8.0),
    ("10pm-6am (Turno 3)", "22:00", "06:00", 8.0),
    ("6am-4:30pm",         "06:00", "16:30", 10.5),
    ("6am-6pm",            "06:00", "18:00", 12.0),
    ("6pm-6am",            "18:00", "06:00", 12.0),
]
SIN_DATO = "No aplica"          # valor del libro cuando no hay dato

MAQUINAS = ["Vinilos_1", "Vinilos_2", "Vinilos_3", "Vinilos_4"]

# Tipo de paro de máquina (columna O "Tipo de paro", catálogo histórico mezclado 2022-2025)
# clave normalizada -> (nombre canónico, pierde_disponibilidad)
TIPOS_PARO_MAQUINA = {
    "no aplica": None,
    "[19] no aplica": None,
    "17. paro de maquina": ("Paro de máquina (sin causa registrada)", False),
    "[18] paro de maquina por ventas": ("Paro de máquina por ventas (sin demanda)", False),
    "9.falta de programacion (planeacion)": ("Falta de programación (planeación)", False),
    "16. paro por proceso anterior": ("Paro por proceso anterior", True),
    "10. paro por materia prima o material de empaque no conforme": ("Materia prima o empaque no conforme", True),
    "[12] materia prima defectuosa o material de empaque no conforme": ("Materia prima o empaque no conforme", True),
    "6. falta de materiales o materias primas": ("Falta de materiales o materias primas", True),
    "[14] falta de materia prima": ("Falta de materiales o materias primas", True),
    "15. aprobacion de laboratorio (microbiologia)": ("Espera aval de laboratorio (microbiología)", True),
    "[13] en espera por el aval del laboratorio de microbiologia": ("Espera aval de laboratorio (microbiología)", True),
    "[09] falta de operario": ("Falta de operario", True),
    "[05] ajuste operativo": ("Ajuste operativo", True),
    "4.ajuste de operacion": ("Ajuste operativo", True),
    "5. aislamiento/cambio de producto": ("Alistamiento / cambio de referencia", True),
    "[07] alistamiento de maquina / cambio de referencia": ("Alistamiento / cambio de referencia", True),
    "3. ajuste electrico o de servicios (aire, caldera, gas)": ("Novedad en servicios (aire, energía, vapor)", True),
    "[03] novedad en los sistemas de potencia (aire, energia, vapor)": ("Novedad en servicios (aire, energía, vapor)", True),
    "11. limpieza no programada": ("Limpieza no programada", True),
}

# Subcódigos de los códigos 1, 3 y 5 -----------------------------------------------------------
SUB_GRUPOS_1 = {
    "1.1": "Sistema alimentador de envases", "1.2": "Sistema de dosificación",
    "1.3": "Sistema de banda de entrada", "1.4": "Sistema de tapado (transfer y pisador de tapa)",
    "1.5": "Sistema de alimentación de tapa", "1.6": "Sistema Video Jet",
    "1.7": "Sistema de sujeción y roscadores", "1.8": "Sistema etiquetadora",
}
SUB_HOJAS_1 = {
    "1.1.A": "Banda", "1.1.B": "Motor", "1.1.C": "Sensor",
    "1.2.A": "Cambio de racores", "1.2.B": "Ajuste de sensor", "1.2.C": "Cambio de válvula",
    "1.2.D": "Retenedores", "1.2.E": "O'Ring",
    "1.3.A": "Banda", "1.3.B": "Motor",
    "1.4.A": "Motor del transfer", "1.4.B": "Pisador de tapa", "1.4.3": "Sensor",
    "1.5.A": "Banda", "1.5.B": "Motor", "1.5.C": "Sensor",
    "1.6.A": "Fotocelda", "1.6.B": "Sensor",
    "1.7.A": "Banda de sujeción", "1.7.B": "Roscadores",
    "1.8.A": "Banda", "1.8.B": "Motor", "1.8.C": "Sensor",
}
SUB_3 = {
    "3.1": "Fallo en la subestación", "3.2": "Fallo en la red pública",
    "3.3": "Falla en la red neumática o el compresor", "3.4": "Falla en la red de enfriamiento o chiller",
    "3.5": "Falla en la red de vapor o caldera",
}
SUB_5 = {
    "5.1": "Sistema alimentador de envases", "5.2": "Sistema de dosificación de pintura, frontal y posterior",
    "5.3": "Banda transportadora de entrada", "5.4": "Banda transportadora de salida",
    "5.5": "Transfer y pisador de tapa", "5.6": "Sistema alimentador de tapa y tobogán",
    "5.7": "Video Jet", "5.8": "Banda de sujeción y roscadores", "5.9": "Sistema de etiquetado",
    "5.10": "Purga de color", "5.11": "Lavado de boquilla",
}
# La numeración antigua del subcódigo 5 (4.x, 2022-2023) estaba desplazada: se re-mapea por nombre.
LEGADO_4_A_5 = {"4.1": "5.1", "4.2": "5.2", "4.3": "5.3", "4.4": "5.5",
                "4.5": "5.6", "4.6": "5.7", "4.7": "5.8", "4.8": "5.9"}

SUBCODIGOS = {1: {**SUB_GRUPOS_1, **SUB_HOJAS_1}, 3: SUB_3, 5: SUB_5}


def sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm_texto(s):
    if s is None or (isinstance(s, float) and s != s):   # None o NaN
        return None
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s or None


def clave_tipo_paro(s):
    s = norm_texto(s)
    return sin_acentos(s).lower() if s else None


def normaliza_subcodigo(codigo: int, texto):
    """Convierte textos sucios ('1.2D  RETENEDORES Y ORING', '4.2  SISTEMA DOSIFICADOR...') a la
    clave canónica del catálogo ('1.2.D', '5.2'). Devuelve None si no se reconoce."""
    t = norm_texto(texto)
    if not t or sin_acentos(t).lower() == "sin especificar":
        return None
    token = t.split(" ")[0].upper()
    token = re.sub(r"(\d)([A-Z])", r"\1.\2", token).rstrip(".")
    if codigo == 5 and token in LEGADO_4_A_5:
        token = LEGADO_4_A_5[token]
    return token if token in SUBCODIGOS.get(codigo, {}) else None


def parse_referencia(nombre: str):
    """'Parchesitos 22cc (6 col)' -> ('Parchesitos', 22, 6)."""
    m = re.match(r"^(.*?)\s*(\d+)\s*cc\s*\((\d+)\s*col\)\s*$", nombre or "", re.I)
    if m:
        return m.group(1).strip(), int(m.group(2)), int(m.group(3))
    m = re.match(r"^(.*?)\s*(\d+)\s*cc\b", nombre or "", re.I)
    return (m.group(1).strip(), int(m.group(2)), None) if m else (nombre, None, None)
