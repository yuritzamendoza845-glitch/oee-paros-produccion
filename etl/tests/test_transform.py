"""Pruebas unitarias del ETL (sin base de datos):  python -m unittest discover -s tests -v"""
import sys, unittest
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "etl"))
import reglas as R
import etl_paros as E


def fila(**kw):
    base = {"fila_origen": 10, "Fecha": pd.Timestamp("2025-03-25"), "Maquina": "Vinilos_3", "Operario": "Diana",
            "Referencia": "Parchesitos 22cc (6 col)", "Pacas producidas": 25.0, "Horas trabajadas": 9.5,
            "Turno": "6am-4:30pm", "Horas no trabajadas": np.nan, "Tipo de paro": "[19] No aplica"}
    base.update(kw)
    return base


def tf(*filas):
    return E.transformar(pd.DataFrame(list(filas)), "t.xlsm")


class Subcodigos(unittest.TestCase):
    def test_variantes_sucias(self):
        self.assertEqual(R.normaliza_subcodigo(1, "1.2D  RETENEDORES Y ORING "), "1.2.D")
        self.assertEqual(R.normaliza_subcodigo(1, "1.2.C Cambio de Valvula"), "1.2.C")
        self.assertEqual(R.normaliza_subcodigo(1, "1.5A BANDA"), "1.5.A")
        self.assertEqual(R.normaliza_subcodigo(1, "1.4.3 Sensor"), "1.4.3")
        self.assertEqual(R.normaliza_subcodigo(3, "3.3 Falla en la red neumática o el compresor"), "3.3")

    def test_legado_4_a_5(self):
        self.assertEqual(R.normaliza_subcodigo(5, "4.2  SISTEMA DOSIFICADOR DE PINTURA"), "5.2")
        self.assertEqual(R.normaliza_subcodigo(5, "4.4  TRANSFER Y PISADOR DE TAPADO"), "5.5")
        self.assertEqual(R.normaliza_subcodigo(5, "4.8 SISTEMA DE ETIQUETADO"), "5.9")

    def test_sin_especificar(self):
        self.assertIsNone(R.normaliza_subcodigo(5, "Sin especificar"))
        self.assertIsNone(R.normaliza_subcodigo(5, np.nan))

    def test_referencia(self):
        self.assertEqual(R.parse_referencia("Parchesitos 22cc (6 col)"), ("Parchesitos", 22, 6))
        self.assertEqual(R.parse_referencia("Parchesitos 125 cc")[1], 125)


class Transformacion(unittest.TestCase):
    def test_despivot_minutos(self):
        reg, paros, rech = tf(fila(**{"Codigo de paro 5": 40.0, "Codigo de paro 16": 70.0, "Subcodigo 5": "5.2 Sistema de dosificación"}))
        self.assertEqual(len(reg), 1)
        self.assertEqual(sorted(paros.motivo_id), [5, 16])
        self.assertEqual(paros.set_index("motivo_id").loc[5, "subcodigo"], "5.2")

    def test_idempotencia_hash(self):
        r1, *_ = tf(fila()); r2, *_ = tf(fila(fila_origen=999))      
        self.assertEqual(r1.row_hash[0], r2.row_hash[0])

    def test_duplicado_exacto_se_marca(self):
        reg, _, rech = tf(fila(), fila(fila_origen=11))
        self.assertEqual(list(reg.calidad_dato), ["OK", "POSIBLE_DUPLICADO"])
        self.assertEqual(len(set(reg.row_hash)), 2)

    def test_rechaza_maquina_y_negativos(self):
        reg, _, rech = tf(fila(Maquina="Vinilos_9"), fila(**{"Codigo de paro 1": -5.0}))
        self.assertEqual(len(reg), 0)
        self.assertEqual(set(rech.regla), {"R02_MAQUINA_DESCONOCIDA", "R03_VALOR_NEGATIVO"})

    def test_unidad_distinta_se_rechaza(self):
        reg, _, rech = tf(fila(**{"Pacas producidas": 4320.0, "Horas trabajadas": 8.0}))
        self.assertEqual(len(reg), 0); self.assertEqual(rech.regla[0], "R05_PACAS_FUERA_DE_RANGO")

    def test_paros_exceden_turno_se_carga_marcado(self):
        reg, *_ = tf(fila(**{"Horas trabajadas": 1.0, "Codigo de paro 6": 120.0, "Pacas producidas": 5.0}))
        self.assertEqual(reg.calidad_dato[0], "REVISAR")

    def test_fila_complemento(self):
        reg, paros, _ = tf(fila(**{"Pacas producidas": np.nan, "Horas trabajadas": np.nan, "Codigo de paro 5": 15.0}))
        self.assertEqual(reg.tipo_registro[0], "COMPLEMENTO_PAROS")

    def test_fila_vacia_se_omite(self):
        reg, *_ = tf(fila(**{"Pacas producidas": np.nan, "Horas trabajadas": np.nan}))
        self.assertEqual(len(reg), 0)

    def test_tipo_paro_legado_se_unifica(self):
        a, *_ = tf(fila(**{"Tipo de paro": "6. FALTA DE MATERIALES O MATERIAS PRIMAS"}))
        b, *_ = tf(fila(**{"Tipo de paro": "[14] Falta de materia prima"}))
        self.assertEqual(a.tipo_paro_maquina[0], b.tipo_paro_maquina[0])


if __name__ == "__main__":
    unittest.main()
