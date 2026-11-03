# Power BI · OEE y paros de producción

Proyecto de Power BI (`.pbip`) con modelo en estrella, 36 medidas DAX y 3 páginas.
**Los datos van incluidos dentro del modelo**: no hay que configurar rutas ni parámetros, ni instalar PostgreSQL.

## Cómo verlo
1. Instale **Power BI Desktop** (gratis, solo Windows). Si pide activar *Proyectos de Power BI (.pbip)*, hágalo en Archivo > Opciones > Características en versión preliminar y reinicie.
2. Abra **`powerbi/OEE.pbip`** (doble clic).
3. Pulse **Actualizar ahora** en el aviso que aparece arriba (o Inicio > Actualizar). Es un solo clic; carga las 10 tablas desde el propio modelo.
4. Opcional: Archivo > Guardar como `.pbix` para tener un solo archivo.

## Qué trae
- **Hechos:** `Fact_Turno`, `Fact_Paros`, `Fact_HorasNoProgramadas`.
- **Dimensiones:** `Dim_Fecha` (tabla de fechas), `Dim_Maquina`, `Dim_Turno`, `Dim_Operaria`, `Dim_Referencia`, `Dim_MotivoParo`. `Meta_Produccion` queda aparte para auditar la meta.
- **Medidas** (tabla `_Medidas`, por carpetas): las 35 de `medidas_oee.dax` más `Última Fecha con Datos`.
- **Páginas:** Resumen OEE · Paros y Pareto · Confiabilidad y TEEP.

## Cifras de control
Sin filtros: OEE ≈ 62,1 %. Por año: 2022 = 52,4 % · 2023 = 58,6 % · 2024 = 69,8 % · 2025 = 68,1 %.
Con 2024 en el filtro: Disponibilidad 80,8 % · Rendimiento 89,6 % · Calidad 100 %.
Utilización de calendario ≈ 91,5 %.
El OEE se calcula como pacas buenas / pacas ideales planificadas (igual que Grafana). Disponibilidad × Rendimiento × Calidad agregados NO dan exactamente el OEE, porque la meta de pacas/hora cambia entre referencias; la medida `Diferencia A x P x Q vs OEE (pp)` muestra esa diferencia.

## Tenga en cuenta
- Los datos terminan el 28/03/2025.
- La meta de pacas/hora es estimada (P90) y `OEE Meta` (75 %) es un valor de ejemplo: reemplácelo por la meta de la planta.
- La Calidad es 100 % porque el libro no registra producto no conforme.
- `Fact_HorasNoProgramadas` incluye todos los turnos de producción. La vista `v_horas_no_programadas` solo sumaba las horas programadas de los turnos con horas perdidas y subestimaba el TEEP; conviene corregirla también.
- Para conectar a PostgreSQL en vez de usar los datos incluidos, use `consultas_powerquery.m` (consultas originales del equipo; no probadas aquí).

## Actualizar los datos
Desde esta carpeta: `python generar_datos.py` (lee `../database/base_datos_oee.sqlite` y crea los CSV de `datos/`) y luego `python incrustar_datos.py` (los mete en el modelo). Cierre Power BI antes de ejecutarlos.
