# 2. Reglas del OEE, supuestos y hallazgos sobre los datos

## 2.1 Definición operativa (aplicada igual en SQL, DAX y Grafana)
| Concepto | Fórmula | Fuente en el libro |
|---|---|---|
| Tiempo programado | `horas_programadas × 60` | *Horas trabajadas* (duración del turno registrado) |
| Tiempo planificado | programado − paros planificados | códigos **15, 16, 17, 18** (*Paro programado* en TABLA CODIGOS) |
| Tiempo operativo | planificado − paros no planificados | códigos **1–14** |
| **Disponibilidad** | operativo / planificado | |
| **Rendimiento** | pacas producidas / (operativo/60 × meta pacas/h) | *Pacas producidas*, meta |
| **Calidad** | (pacas − no conformes) / pacas | no conformes (ver 2.2) |
| **OEE** | A × P × Q = pacas buenas / (planificado/60 × meta) | |
| TEEP | OEE × horas programadas / (programadas + no programadas) | *Horas no trabajadas* |

Los porcentajes agregados se calculan siempre desde sumas (media ponderada), nunca promediando porcentajes.
Hallazgo clave: `Horas trabajadas + Horas no trabajadas ≈ 24 h` (p. ej. 10,5 + 13,5), es decir, las "no trabajadas" son calendario **fuera de programación**
(sin ventas, sin programación…); por eso **no** restan Disponibilidad y se reportan aparte (TEEP y causa en `v_horas_no_programadas`).
La eficiencia del Excel (`Tiempos!C8 = pacas / (horas × meta)`) es contra tiempo bruto; el OEE de este proyecto lo es contra tiempo planificado, así que **no son comparables 1 a 1**.

## 2.2 Supuestos que deben validarse con la empresa (están parametrizados, no escondidos)
1. **Meta de producción.** El libro no guarda la *Meta por hora* (columna vacía; el formulario físico sí la trae, p. ej. 52 pacas/h en Rojo 125 cc). Se usa el **percentil 90 del ritmo observado en tiempo operativo**
   por máquina/referencia (≥10 observaciones; si no, el de la máquina) → `meta_produccion.origen = 'ESTIMADA_P90'`. Con una meta oficial, basta cargarla con `origen = 'OFICIAL'`: el ETL no la pisa y todo se recalcula.
   Consecuencia: el Rendimiento mide cercanía al *mejor ritmo demostrado*, no a la capacidad nominal; pueden verse valores >100 % por turno.
2. **Calidad.** El libro no registra producto no conforme → `pacas_no_conformes = 0` y **Calidad = 100 %**. El OEE actual es, en la práctica, A × P. La columna y la lógica ya existen; cuando Calidad entregue el dato, el OEE se ajusta sin tocar código.
   (Los códigos 11 *Reproceso* y 12 *Materia prima defectuosa* se tratan como paros, no como pérdida de calidad.)
3. **Planificado vs. no planificado** sigue TABLA CODIGOS (15–17); el 18 *Desinfección* se asumió planificado; el 4 *Mantenimiento preventivo* quedó como no planificado por seguir la fuente (muchas plantas lo consideran planificado: se cambia en `dim_motivo_paro.es_planificado`, queda auditado).
4. Las filas `COMPLEMENTO_PAROS` sin fila de producción del mismo turno/operaria/referencia (1.274 de 3.217) **no entran al OEE** (no hay tiempo programado contra el cual medirlas) pero **sí al Pareto**.
5. "Tipo de paro" de máquina: *sin ventas / falta de programación / paro de máquina* = causa de demanda; el resto = causa operativa (`pierde_disponibilidad`).

## 2.3 Reglas de validación del ETL
| Regla | Severidad | Acción |
|---|---|---|
| R01 fecha inválida/futura · R02 máquina desconocida · R03 valores negativos · R04 horas > 24 | ERROR | rechaza fila |
| R05 pacas/hora > 400 (unidad distinta: unidades sueltas) | ERROR | rechaza fila |
| R06 paros > duración del turno (+5 min) | WARNING | carga marcada `REVISAR` |
| R07 contenido idéntico repetido | WARNING | carga marcada `POSIBLE_DUPLICADO` (excluida del OEE) |
| R08 tipo de paro no catalogado · R09 subcódigo no reconocido · R10 turno no catalogado | WARNING | carga con valor nulo/«Sin dato» |

## 2.4 Resultado de ejecutar el ETL sobre `SEGUIMIENTO_TEMPERAS_Y_VINILOS_Actividad.xlsm`
8.208 filas leídas → 232 vacías omitidas → **7.965 registros válidos** (4.748 producción + 3.217 complementos) y **16.504 detalles de paro**;
11 rechazos (R05: ocho filas de Vinilos_1, jul-2023, con 3.500–9.400 «pacas» en 8 h); 3 `REVISAR`; 43 `POSIBLE_DUPLICADO`. Rango 2022-01-01 → 2025-03-28.
Otros hallazgos de calidad: 3.912 filas sin turno y 3.721 sin operaria (casi todo 2022–2023: el formato era a nivel máquina-día); la numeración de subcódigo 5 era 4.x hasta 2023 (reasignada por nombre);
el tipo de paro mezclaba dos catálogos (numerado 3–17 y `[xx]`), unificados en 12 categorías; los subcódigos del código 1 venían en ≥ 40 grafías.

### OEE de referencia (implementación pandas independiente `etl/oee_referencia.py`, meta P90, Calidad = 100 %)
| Año | Disponibilidad | Rendimiento | OEE |
|---|---|---|---|
| 2022 | 91,7 % | 58,3 % | 52,4 % |
| 2023 | 85,1 % | 70,1 % | 58,6 % |
| 2024 | 80,8 % | 89,6 % | 69,8 % |
| 2025 (hasta 28-mar) | 78,5 % | 91,2 % | 68,1 % |

| Máquina | Disponibilidad | Rendimiento | OEE |
|---|---|---|---|
| Vinilos_1 | 80,4 % | 72,8 % | 58,9 % |
| Vinilos_2 | 75,4 % | 67,8 % | 51,4 % |
| Vinilos_3 | 87,1 % | 80,6 % | 70,6 % |
| Vinilos_4 | 86,9 % | 83,0 % | 72,5 % |

Lectura: la Disponibilidad **baja** año a año (91,7 → 78,5 %) mientras el Rendimiento sube; el 2022 es optimista porque en ese año casi no hay detalle de paros (formato antiguo). Vinilos_2 (envase de 125 cc) es la de menor OEE.

### Pareto de paros no planificados (5.537 h, sin copias duplicadas)
| Código | Horas | % | % acum. |
|---|---|---|---|
| [05] Ajuste operativo | 1.809 | 32,7 | 32,7 |
| [06] Limpieza por derrame / tiempo sin reportar | 1.546 | 27,9 | 60,6 |
| [07] Alistamiento / cambio de referencia | 621 | 11,2 | 71,8 |
| [10] Ventaja / evacuación / calidad | 356 | 6,4 | 78,2 |
| [01] Falla electromecánica / control | 321 | 5,8 | 84,0 |

Cuatro códigos (05, 06, 07, 10) explican ~78 % de las horas perdidas; dentro del [05], el subsistema 5.2 (dosificación de pintura) concentra ~40 % de los eventos.
**Ojo:** el [06] incluye «tiempo sin reportar» (así se llama en el formulario), por lo que parte de esas horas es una brecha de registro, no un derrame real.
