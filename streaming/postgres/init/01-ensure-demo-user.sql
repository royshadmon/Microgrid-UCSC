-- Ensure the AnyLog operator's expected DB user exists.
-- The AnyLog operator base config sets DB_USER=demo / DB_PASSWD=passwd and
-- connects to database "customers". POSTGRES_DB=customers (in postgres.env)
-- already creates that database; this script just adds the demo user with
-- full privileges so the operator can write its tables.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'demo') THEN
    CREATE ROLE demo WITH LOGIN PASSWORD 'passwd' SUPERUSER;
  END IF;
END$$;

GRANT ALL PRIVILEGES ON DATABASE customers TO demo;
