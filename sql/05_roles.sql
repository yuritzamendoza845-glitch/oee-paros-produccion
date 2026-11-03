-- Roles de mínimo privilegio. Cambie las contraseñas ANTES de ejecutar (o use \password después).
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'oee_lectura') THEN CREATE ROLE oee_lectura LOGIN PASSWORD 'CAMBIAR_ME'; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'oee_etl')     THEN CREATE ROLE oee_etl     LOGIN PASSWORD 'CAMBIAR_ME'; END IF;
END $$;

-- Lectura (Grafana / Power BI): solo vistas, dimensiones y estado del pipeline
GRANT USAGE ON SCHEMA oee, etl TO oee_lectura;
GRANT SELECT ON ALL TABLES IN SCHEMA oee TO oee_lectura;
GRANT SELECT ON etl.v_estado_pipeline TO oee_lectura;
GRANT EXECUTE ON FUNCTION oee.fn_pareto_paros(date, date, text, boolean) TO oee_lectura;
ALTER DEFAULT PRIVILEGES IN SCHEMA oee GRANT SELECT ON TABLES TO oee_lectura;

-- ETL: escribe en stg/etl y ejecuta los procedimientos (que corren con sus privilegios)
GRANT USAGE ON SCHEMA oee, stg, etl, audit TO oee_etl;
GRANT ALL ON ALL TABLES IN SCHEMA stg, etl TO oee_etl;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA oee TO oee_etl;
GRANT INSERT ON audit.log_cambios TO oee_etl;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA oee, stg, etl, audit TO oee_etl;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA etl, oee, audit TO oee_etl;
GRANT EXECUTE ON ALL PROCEDURES IN SCHEMA etl TO oee_etl;
