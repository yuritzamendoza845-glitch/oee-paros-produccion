// =====================================================================================
// Power Query (M) — Obtener datos > Base de datos PostgreSQL (modo Importar).
// Cree el parámetro  pServidor = "host:5432"  y  pBase = "oee"  (Administrar parámetros).
// Use el rol de solo lectura oee_lectura. Cada bloque `// ===` es UNA consulta con ese nombre.
// Todas leen vistas/tablas de PostgreSQL => la lógica vive en la BD, no se duplica en Power BI.
// =====================================================================================

// === Fuente (consulta auxiliar, deshabilite la carga)
let
    Fuente = PostgreSQL.Database(pServidor, pBase, [CreateNavigationProperties = false])
in
    Fuente

// === Fact_Turno   (grano: fecha-máquina-turno-operaria-referencia)
let
    t = Fuente{[Schema = "oee", Item = "v_oee_turno"]}[Data],
    tipos = Table.TransformColumnTypes(t, {{"fecha", type date}, {"min_programados", type number},
            {"min_planificados", type number}, {"min_paro_planificado", type number},
            {"min_paro_no_planificado", type number}, {"min_operativos", type number},
            {"pacas_producidas", type number}, {"pacas_buenas", type number},
            {"pacas_ideales_operativas", type number}, {"pacas_ideales_planificadas", type number},
            {"horas_no_programadas", type number}}),
    sinCalculados = Table.RemoveColumns(tipos, {"disponibilidad", "rendimiento", "calidad", "oee"})  // los KPI se calculan en DAX
in
    sinCalculados

// === Fact_Paros   (grano: una fila por registro × código de paro)
let
    t = Fuente{[Schema = "oee", Item = "v_paros_detalle"]}[Data],
    cols = Table.SelectColumns(t, {"detalle_id", "fecha", "maquina_id", "turno_id", "operario_id", "referencia_id",
                                   "motivo_id", "subcodigo_clave", "subcodigo", "area_involucrada", "minutos", "horas"})
in
    cols

// === Fact_HorasNoProgramadas
let t = Fuente{[Schema = "oee", Item = "v_horas_no_programadas"]}[Data] in t

// === Dim_Fecha  (tabla de calendario de la BD; márquela como tabla de fechas)
let t = Fuente{[Schema = "oee", Item = "dim_fecha"]}[Data] in t

// === Dim_Maquina
let t = Table.SelectColumns(Fuente{[Schema = "oee", Item = "dim_maquina"]}[Data], {"maquina_id", "nombre", "linea"}) in
    Table.RenameColumns(t, {{"nombre", "Máquina"}})

// === Dim_Turno
let t = Table.SelectColumns(Fuente{[Schema = "oee", Item = "dim_turno"]}[Data], {"turno_id", "nombre", "horas_nominales"}) in
    Table.RenameColumns(t, {{"nombre", "Turno"}})

// === Dim_Operaria
let t = Table.SelectColumns(Fuente{[Schema = "oee", Item = "dim_operario"]}[Data], {"operario_id", "nombre"}) in
    Table.RenameColumns(t, {{"nombre", "Operaria/o"}})

// === Dim_Referencia
let t = Table.SelectColumns(Fuente{[Schema = "oee", Item = "dim_referencia"]}[Data], {"referencia_id", "nombre", "marca", "volumen_cc", "num_colores"}) in
    Table.RenameColumns(t, {{"nombre", "Referencia"}, {"marca", "Marca"}, {"volumen_cc", "Volumen (cc)"}, {"num_colores", "Colores"}})

// === Dim_MotivoParo  (denormalizada con el área de impacto => esquema estrella puro)
let
    m = Fuente{[Schema = "oee", Item = "dim_motivo_paro"]}[Data],
    a = Fuente{[Schema = "oee", Item = "dim_area_impacto"]}[Data],
    j = Table.NestedJoin(m, {"area_id"}, a, {"area_id"}, "a", JoinKind.LeftOuter),
    x = Table.ExpandTableColumn(j, "a", {"nombre"}, {"Área de impacto"}),
    et = Table.AddColumn(x, "Etiqueta", each "[" & Text.PadStart(Text.From([motivo_id]), 2, "0") & "] " & [nombre], type text),
    r = Table.RenameColumns(et, {{"nombre", "Motivo"}, {"es_planificado", "Es planificado"}, {"categoria_oee", "Categoría OEE"}})
in
    r

// === Meta_Produccion  (para auditar el origen de la meta: OFICIAL vs ESTIMADA_P90)
let t = Fuente{[Schema = "oee", Item = "meta_produccion"]}[Data] in t
