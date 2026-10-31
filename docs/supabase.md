# Lorebook on a shared Supabase

Lorebook needs PostgreSQL with pgvector. On a server that already runs Supabase it uses that
PostgreSQL, isolated from everything else:

- its own **schema** `lorebook` (all tables, the Alembic version table);
- its own **role** `lorebook`: owns that schema only, no superuser, no access to `public`
  or any other schema, at most 5 connections;
- the app connects directly to the `supabase-db-...` container over Supabase's Docker network
  (nothing is published to the internet), keeps a pool of 4 connections, and sets
  `search_path=lorebook,extensions,public` (pgvector lives in `extensions` in Supabase).

## One-time setup (run as `supabase_admin`, e.g. in the Terminal of the db container)

```sql
CREATE ROLE lorebook LOGIN PASSWORD '<generated>' CONNECTION LIMIT 8;
CREATE SCHEMA lorebook AUTHORIZATION lorebook;
GRANT USAGE ON SCHEMA extensions TO lorebook;   -- the vector type and its operators
REVOKE ALL ON SCHEMA public FROM lorebook;
ALTER ROLE lorebook SET statement_timeout = '120s';
```

pgvector must already be installed (`SELECT extname FROM pg_extension WHERE extname='vector'`);
the role cannot install extensions, and the app only checks for it.

## App environment

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql://lorebook:<password>@supabase-db-<id>:5432/postgres` |
| `DB_SCHEMA` | `lorebook` |
| `SUPABASE_NETWORK` | the Docker network name of the Supabase service |
| `SECRET_KEY`, `ALLOWED_EMAILS`, `OWNER_EMAILS`, `PUBLIC_URL`, `SMTP_*` | as in the README |

## Moving to a plain pgvector server

Use `docker-compose.yml` (own `db` container) or any PostgreSQL with pgvector: set
`DATABASE_URL`, leave `DB_SCHEMA` empty. To carry the data over:
`pg_dump -n lorebook --no-owner` from Supabase, restore into the new database
(a `lorebook` schema is fine there too: keep `DB_SCHEMA=lorebook`).

## Removing Lorebook from Supabase

`DROP SCHEMA lorebook CASCADE; DROP ROLE lorebook;` touches nothing else.
