#!/bin/bash
# Creates the DB role the MCP server connects as. This is the DB-permission-level
# layer of the read-only guardrail (see README "defense in depth"): even if the
# app-level SQL guardrail in the MCP server had a bug, Postgres itself will refuse
# writes for this role.
set -euo pipefail

: "${MCP_READONLY_PASSWORD:?MCP_READONLY_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE mcp_reader LOGIN PASSWORD '${MCP_READONLY_PASSWORD}'
        NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
        CONNECTION LIMIT 10;

    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO mcp_reader;
    GRANT USAGE ON SCHEMA public TO mcp_reader;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO mcp_reader;

    -- Any table added later is read-only for mcp_reader too, no manual re-grant needed.
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mcp_reader;

    -- Belt-and-suspenders DB-level enforcement: writes fail even if the app-level
    -- SQL guardrail were ever bypassed.
    ALTER ROLE mcp_reader SET default_transaction_read_only = on;

    -- DB-level cost guardrail, mirrors the app-level statement timeout.
    ALTER ROLE mcp_reader SET statement_timeout = '5000';
EOSQL
