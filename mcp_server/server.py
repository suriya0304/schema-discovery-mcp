"""MCP server that exposes a read-only view of the delivery-tracker Postgres
database to an LLM agent as three tools: list_tables, describe_schema and
run_query.

Credentials (PG_PASSWORD etc.) are read from the process environment only
(see config.py / docker-compose.yml) and never appear in a tool's return
value, in this module's logging, or anywhere an LLM prompt could see them.
The agent process on the other side of this MCP connection has no database
credentials of its own — it only ever calls these tools.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import psycopg
from mcp.server.fastmcp import Context, FastMCP
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import settings
from guardrails import GuardrailViolation, cap_rows, enforce_read_only_select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("delivery_tracker_mcp")


@dataclass
class AppContext:
    pool: AsyncConnectionPool


@retry(
    retry=retry_if_exception_type(psycopg.OperationalError),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(8),
    reraise=True,
)
async def _open_pool() -> AsyncConnectionPool:
    """Open the pool, retrying while Postgres is still starting up.

    docker-compose's `depends_on: service_started` does not wait for
    Postgres to finish accepting connections, so the first few attempts
    right after container start are expected to fail transiently.
    """
    pool = AsyncConnectionPool(
        conninfo=settings.conninfo,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"row_factory": dict_row},
    )
    await pool.open(wait=True, timeout=10)
    return pool


@asynccontextmanager
async def app_lifespan(_server: FastMCP) -> AsyncIterator[AppContext]:
    logger.info("Connecting to Postgres as read-only role %r ...", settings.pg_user)
    pool = await _open_pool()
    logger.info("Connected. Pool ready.")
    try:
        yield AppContext(pool=pool)
    finally:
        await pool.close()


mcp = FastMCP(
    name="delivery-tracker-db",
    instructions=(
        "Read-only access to the delivery-tracker database (squads, contributors, "
        "initiatives, tickets, ticket_comments). Always call list_tables and "
        "describe_schema before writing SQL — do not assume column names."
    ),
    host=settings.mcp_host,
    port=settings.mcp_port,
    lifespan=app_lifespan,
)


def _pool(ctx: Context) -> AsyncConnectionPool:
    return ctx.request_context.lifespan_context.pool


@mcp.tool()
async def list_tables(ctx: Context) -> list[dict]:
    """List all tables in the public schema with a short description and row count.

    Call this first, before describe_schema or run_query, to discover what
    data is available. Do not assume table names.
    """
    sql = """
        SELECT c.relname AS table_name,
               obj_description(c.oid) AS description,
               c.reltuples::bigint AS approx_row_count
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        ORDER BY c.relname;
    """
    pool = _pool(ctx)
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(sql)
        return await cur.fetchall()


@mcp.tool()
async def describe_schema(ctx: Context, table_name: str | None = None) -> dict:
    """Describe columns, types, primary keys and foreign keys.

    Args:
        table_name: If given, describe only this table. If omitted, describe
            every table in the public schema (use this sparingly — prefer
            passing a specific table_name once you know which tables you need,
            to keep the context small).
    """
    columns_sql = """
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND (%(table_name)s::text IS NULL OR table_name = %(table_name)s)
        ORDER BY table_name, ordinal_position;
    """
    # Deliberately queries pg_catalog rather than information_schema: the
    # information_schema.table_constraints/key_column_usage views only show
    # rows for tables where the current role has more than SELECT (e.g.
    # REFERENCES) — by SQL-standard design they hide constraint metadata from
    # pure read-only roles. mcp_reader is intentionally SELECT-only (see
    # db/init/03_readonly_role.sh), so we read the same information straight
    # from pg_constraint/pg_attribute, which carry the ordinary table-level
    # SELECT grant like everything else in this schema.
    fk_sql = """
        SELECT
            c.relname  AS table_name,
            a.attname  AS column_name,
            fc.relname AS references_table,
            fa.attname AS references_column
        FROM pg_constraint con
        JOIN pg_class c ON c.oid = con.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_class fc ON fc.oid = con.confrelid
        JOIN unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
        JOIN unnest(con.confkey) WITH ORDINALITY AS fk(attnum, ord) ON fk.ord = k.ord
        JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
        JOIN pg_attribute fa ON fa.attrelid = con.confrelid AND fa.attnum = fk.attnum
        WHERE con.contype = 'f'
          AND n.nspname = 'public'
          AND (%(table_name)s::text IS NULL OR c.relname = %(table_name)s)
        ORDER BY c.relname, k.ord;
    """
    pk_sql = """
        SELECT c.relname AS table_name, a.attname AS column_name
        FROM pg_constraint con
        JOIN pg_class c ON c.oid = con.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN unnest(con.conkey) AS k(attnum) ON true
        JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
        WHERE con.contype = 'p'
          AND n.nspname = 'public'
          AND (%(table_name)s::text IS NULL OR c.relname = %(table_name)s)
        ORDER BY c.relname, a.attnum;
    """
    params = {"table_name": table_name}
    pool = _pool(ctx)
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(columns_sql, params)
            columns = await cur.fetchall()
        async with conn.cursor() as cur:
            await cur.execute(pk_sql, params)
            primary_keys = await cur.fetchall()
        async with conn.cursor() as cur:
            await cur.execute(fk_sql, params)
            foreign_keys = await cur.fetchall()

    if not columns:
        raise ValueError(
            f"No such table: {table_name!r}. Call list_tables to see available tables."
        )

    return {"columns": columns, "primary_keys": primary_keys, "foreign_keys": foreign_keys}


@mcp.tool()
async def run_query(ctx: Context, sql: str, row_limit: int = 50) -> dict:
    """Execute a single read-only SQL SELECT statement against the database.

    Guardrails (enforced here, in addition to the DB role itself being
    read-only): only one SELECT/CTE statement per call; no INSERT/UPDATE/
    DELETE/DROP/ALTER/etc; results are always capped at `row_limit` rows
    (server-side maximum applies regardless of what you request).

    If this raises an error (bad column name, syntax error, ambiguous
    column, etc.), read the error message, call describe_schema again if
    needed, and retry with a corrected query.

    Args:
        sql: A single SELECT statement (CTEs with WITH are allowed).
        row_limit: Max rows to return (capped server-side at settings.max_rows).
    """
    try:
        clean_sql = enforce_read_only_select(sql)
    except GuardrailViolation as exc:
        raise ValueError(f"Query rejected by read-only guardrail: {exc}") from exc

    capped_limit = max(1, min(row_limit, settings.max_rows))
    guarded_sql = cap_rows(clean_sql, capped_limit)

    pool = _pool(ctx)
    try:
        async with pool.connection() as conn:
            await conn.execute("SET TRANSACTION READ ONLY")
            async with conn.cursor() as cur:
                await cur.execute(guarded_sql)
                rows = await cur.fetchall()
    except psycopg.errors.ReadOnlySqlTransaction as exc:
        # Defense-in-depth: even if the app-level guardrail above had a gap,
        # the mcp_reader role itself cannot write (see 03_readonly_role.sh).
        raise ValueError(f"Database rejected this as a write attempt: {exc}") from exc
    except psycopg.Error as exc:
        # Surfaced back to the LLM as a failed tool call so it can self-correct
        # (bad column name, ambiguous reference, type mismatch, etc.).
        raise ValueError(f"SQL error: {exc}") from exc

    return {
        "row_count": len(rows),
        "rows": rows,
        "truncated": len(rows) >= capped_limit,
        "row_limit_applied": capped_limit,
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
