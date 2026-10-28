# Postgres

`streaming/postgres/` — the relational store that AnyLog's operator persists rows into. AnyLog handles the SQL itself; we only have to bring the database up with the right user, password, and database name.

```
streaming/postgres/
├── docker-compose.yaml             # standalone Postgres bring-up (debugging)
├── postgres.env.example            # credentials template (copy to postgres.env)
└── init/
    └── 01-ensure-demo-user.sql     # creates the AnyLog operator's DB user on first boot
```

## Main contents

**`docker-compose.yaml`** — `postgres:14.0-alpine` as `postgres1`, port `5432` exposed, named volume `pgdata`. Reference-only; the production root `docker-compose.yaml` inlines an equivalent service. Use this file when you want Postgres up by itself for debugging:

```bash
docker compose -f streaming/postgres/docker-compose.yaml up -d
```

**`postgres.env.example`** — template that gets copied to `postgres.env` at deploy time. The DB credentials here must match `DB_USER` / `DB_PASSWD` in the operator's `base_configs.env`:

```env
POSTGRES_USER=admin
POSTGRES_PASSWORD=passwd
POSTGRES_DB=customers
POSTGRES_INITDB_ARGS=--auth=md5
```

**`init/01-ensure-demo-user.sql`** — runs once on first boot (Postgres's standard `docker-entrypoint-initdb.d` hook). Creates the `demo` superuser that the AnyLog operator expects:

```sql
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'demo') THEN
    CREATE ROLE demo WITH LOGIN PASSWORD 'passwd' SUPERUSER;
  END IF;
END$$;

GRANT ALL PRIVILEGES ON DATABASE customers TO demo;
```

`POSTGRES_DB=customers` causes the `customers` database to be created automatically; this script only ensures the `demo` role exists with the right password and privileges so the operator can write `egauge_kafka`, `nilm_disaggregated`, and the partition tables.

## Use in the project

The operator's `base_configs.env` is hard-wired to:

```env
DB_TYPE=psql
DB_USER=demo
DB_PASSWD=passwd
DB_IP=host.docker.internal
DB_PORT=5432
```

So the operator container reaches out to `host.docker.internal:5432` and logs in as `demo/passwd` to the `customers` database — which is exactly what this folder creates. Two account names are in play:

- `admin/passwd` — Postgres superuser created by `POSTGRES_USER`; used for root-level admin work.
- `demo/passwd` — AnyLog operator account created by the init script; all AnyLog reads/writes use this.

Everything the IEMS reads — `egauge_kafka`, `nilm_disaggregated`, and the `par_*_d14_insert_timestamp` partitions — ultimately lives in this Postgres instance; the IEMS code only ever sees it through AnyLog's REST layer (`services/iems/load/anylog_query.py`), never via psycopg2.
