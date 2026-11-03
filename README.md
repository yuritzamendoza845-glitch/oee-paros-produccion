# Arquitectura de datos para OEE y paros de producción

Trabajo de **Inteligencia de Negocios** · Institución Universitaria Pascual Bravo
Docente: Ramiro Grisales
Integrantes: Yuritza Mendoza, Laura Mejía

## ¿De qué trata?

En la línea de vinilos y témperas, los paros de las máquinas se anotan a mano y se pasan a un libro de Excel. Este proyecto organiza esa información en una base de datos PostgreSQL, la carga automáticamente con un proceso en Python y la muestra en tableros de Grafana y Power BI, para medir el **OEE** (la eficiencia con que se aprovechan las máquinas) y encontrar las causas de los paros.

## ¿Qué contiene?

| Carpeta | Contenido |
|---|---|
| `database/` | La base de datos con los datos cargados (script de PostgreSQL y copia en SQLite) |
| `sql/` | Esquema, catálogos, triggers, procedimientos almacenados y vistas del OEE |
| `etl/` | Proceso en Python que lee el Excel, lo limpia, lo valida y lo carga sin duplicados |
| `grafana/` | Tablero operativo y alertas |
| `powerbi/` | Proyecto de Power BI listo para abrir (`OEE.pbip`, datos incluidos en el modelo, sin configurar rutas), con medidas DAX y 3 páginas; incluye también las consultas de Power Query originales para PostgreSQL |
| `tests/` | Pruebas del proceso ETL |
| `docs/` | Informe completo del trabajo y documentación técnica |
| `data/processed/` | Salidas del ETL en modo de prueba y OEE de referencia (CSV) |
| `docker-compose.yml` | Levanta PostgreSQL y Grafana con todo precargado |

## Resultados principales

- Se cargaron 7.965 registros de producción y 16.504 detalles de paro (2022 a marzo de 2025).
- El OEE de referencia pasó de 52 % en 2022 a 70 % en 2024.
- Cuatro códigos de paro (05, 06, 07 y 10) explican cerca del 78 % de las horas perdidas.

## Cómo usarlo

**Cargar la base de datos en PostgreSQL:**

```bash
createdb oee
psql -d oee -v ON_ERROR_STOP=1 -f database/base_datos_oee_postgres.sql
```

**Ver el tablero de Grafana con Docker (lo más rápido):**

```bash
docker compose up -d
```

Abra http://localhost:3000 (usuario `admin`, clave `admin`) y entre al tablero *oee-operativo* de la carpeta *Planta Vinilos*. Cambie el rango de tiempo a **2022-01-01 → 2025-03-28**, porque los datos terminan en marzo de 2025.

**Probar el proceso ETL sin tocar la base de datos:**

```bash
pip install -r etl/requirements.txt
python etl/etl_paros.py --archivo ARCHIVO.xlsm --dry-run
```

**Correr las pruebas:**

```bash
python -m unittest discover -s tests -v
```

## Informe

El documento completo está en [`docs/Documentacion_OEE_Paros_Produccion.docx`](docs/Documentacion_OEE_Paros_Produccion.docx).

## Limitaciones

- La meta de producción por hora se estimó a partir de los datos, porque el libro no la guarda.
- La Calidad se asume en 100 %, porque no hay registro de producto no conforme.
- Los scripts de SQL y el tablero de Grafana deben probarse en un entorno real. Las medidas y datos del proyecto de Power BI se contrastaron con las cifras de referencia, pero sus gráficos conviene revisarlos en Power BI Desktop.
