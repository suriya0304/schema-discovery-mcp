# Delivery Tracker — MCP Database Connector + Agentic Retrieval

A small, dockerized system that lets an LLM answer natural-language questions
about a Postgres database *without ever holding a database credential or
being able to run arbitrary SQL*. The database is exposed to the LLM only
through an MCP (Model Context Protocol) server, and a LangGraph agent drives
a plan → act → observe loop on top of it.

This is Task 2 of the assessment, built against a new domain (a product
engineering delivery tracker — squads / contributors / initiatives / tickets
/ ticket_comments) rather than the literal employees/projects/issues example,
while still supporting the same kinds of questions the brief asks for.

## Architecture

```
┌────────────────────┐        HTTP (FastAPI)         ┌───────────────────────┐
│   You / demo.py     │ ─────────────────────────────▶│      agent-api        │
│  "Which AI-team      │                                │  (LangGraph agent,    │
│   members have open  │◀─────────────────────────────  │   OpenAI model)       │
│   issues on Atlas?"  │      grounded NL answer        │  NO DB credentials    │
└────────────────────┘                                └──────────┬────────────┘
                                                                   │ MCP
                                                       (streamable-HTTP, tools:
                                                        list_tables /
                                                        describe_schema /
                                                        run_query)
                                                                   │
                                                        ┌──────────▼────────────┐
                                                        │      mcp-server        │
                                                        │  read-only SQL guard-  │
                                                        │  rail, row cap,        │
                                                        │  statement timeout     │
                                                        │  (only process that    │
                                                        │   holds a DB password) │
                                                        └──────────┬────────────┘
                                                                   │ psycopg,
                                                                   │ role = mcp_reader
                                                                   │ (SELECT-only,
                                                                   │  default_transaction
                                                                   │  _read_only = on)
                                                        ┌──────────▼────────────┐
                                                        │      db (Postgres)     │
                                                        │  squads, contributors, │
                                                        │  initiatives, tickets, │
                                                        │  ticket_comments       │
                                                        └────────────────────────┘
```

Three containers (`docker-compose.yml`):

| Service      | Holds                                   | Never holds                          |
|--------------|------------------------------------------|---------------------------------------|
| `db`         | all data, the `app_admin` superuser (init only) and the `mcp_reader` role | — |
| `mcp-server` | the `mcp_reader` **password** (env var only) | any code path that lets a caller run non-SELECT SQL |
| `agent-api`  | the OpenAI API key                        | **any database credential, host, or connection string** |

## Quickstart

```bash
cp .env.example .env
# edit .env: set POSTGRES_PASSWORD, MCP_READONLY_PASSWORD, OPENAI_API_KEY

docker compose up -d --build

curl -s -X POST http://localhost:8080/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Fetch contributor details where department is AI."}'

# full demo (guardrail checks + both required example questions +
# a clarification round-trip + an error-recovery example):
docker compose exec agent-api python demo.py
```

`demo.py` makes ~5 LLM calls. With the default model (`gpt-4o-mini`) this
costs a small fraction of a cent to a few cents total — see "Model choice"
below for why that's the default.

## The domain

Not the literal employees/projects/issues example — a product-engineering
delivery tracker instead, with the same *shape* (people → teams → projects →
issues) so the brief's example questions still apply:

- **squads** — teams, each with a `focus_area` (`AI`, `Platform`, `Growth`,
  `Security`) — this is what the brief calls "department".
- **contributors** — people, each belonging to a squad.
- **initiatives** — projects, each owned by a squad.
- **tickets** — issues, each belonging to an initiative, with a reporter and
  an (optional) assignee, a status (`open`/`in_progress`/`blocked`/`closed`)
  and priority.
- **ticket_comments** — a fifth table, discussion on a ticket, to keep the
  schema a step beyond the minimal three-table case.

See `db/init/01_schema.sql` / `02_seed.sql` for the full DDL and ~16
contributors / 6 initiatives / 22 tickets / 8 comments of sample data.

## MCP configuration & connector flow

The MCP server (`mcp_server/server.py`) is built with the official `mcp`
Python SDK's `FastMCP`, run over **streamable-HTTP** (not stdio) so it can
live in its own container and be reached over the docker-compose network at
`http://mcp-server:8000/mcp`. It exposes exactly three tools:

1. **`list_tables`** — discovers what tables exist (queried from
   `pg_catalog`, not hard-coded).
2. **`describe_schema(table_name?)`** — columns, types, primary keys and
   foreign keys for one table or all of them.
3. **`run_query(sql, row_limit?)`** — executes a single read-only SELECT,
   enforced (see below), and returns rows as JSON.

Flow for one question:

1. Agent calls `list_tables` → learns the five table names.
2. Agent calls `describe_schema` for each table it plans to touch → learns
   real column names and FK relationships (e.g. `tickets.assignee_id →
   contributors.id`).
3. Agent composes a SELECT (possibly with JOINs) and calls `run_query`.
4. mcp-server validates, rewrites (row cap), executes as `mcp_reader`, and
   returns rows — or an error, which becomes an observation, not a crash.
5. Agent repeats 3–4 if it got an error or an ambiguous/empty result, then
   answers in natural language, grounded in the returned rows.

### How credentials stay out of the agent

`agent/app/config.py` has no field for a database host, user, or password —
structurally, not just by convention. The only thing the agent process knows
is `MCP_SERVER_URL`, an HTTP endpoint. `mcp_server/config.py` is the only
place `PG_PASSWORD` is read, and it comes from the `mcp-server` container's
own environment (`docker-compose.yml`), populated from `.env`. The LLM's
system prompt (`agent/app/graph.py`) never mentions a connection string
because there isn't one to mention — the model can't leak, misuse, or be
tricked into using a credential it was never given.

## Read-only enforcement: defense in depth

Three independent layers, in case any one of them has a bug:

1. **Prompt-level** (weakest, advisory only): the system prompt tells the
   model to write only SELECT statements. This is not trusted as a security
   boundary — it's there so the *common case* doesn't even attempt a write
   and waste a round-trip.
2. **MCP-tool-level** (`mcp_server/guardrails.py`): every `run_query` call is
   parsed with `sqlparse`. Rejected unless it is exactly one statement whose
   first token is `SELECT` or `WITH`; a keyword blocklist (`INSERT`,
   `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT`, `CREATE`, `COPY`,
   `EXECUTE`, `DO`, …) is also scanned for, both via the parsed token stream
   and a raw regex pass (belt-and-suspenders against parser edge cases).
   Whatever survives is wrapped as `SELECT * FROM (<query>) AS _sub LIMIT n`
   — a hard row cap regardless of what the query itself requested.
3. **DB-permission-level** (`db/init/03_readonly_role.sh`, strongest): the
   role `mcp_reader` that the MCP server connects as has **only** `SELECT`
   granted on the schema (`GRANT SELECT ... ; ALTER DEFAULT PRIVILEGES ...`
   for future tables too), plus `ALTER ROLE mcp_reader SET
   default_transaction_read_only = on`. Even a query that somehow slipped
   past layer 2 would be rejected by Postgres itself with "cannot execute
   ... in a read-only transaction" — verified in the guardrail smoke test in
   `demo.py`.

Cost guardrail, same layering idea: `statement_timeout` is set both at the
role level (`ALTER ROLE ... SET statement_timeout`) and per-connection in the
MCP server (`options='-c statement_timeout=...'`), and every `run_query`
result is capped at `MAX_ROWS` (default 200) regardless of the caller's
requested `row_limit`.

**Where does safety live?** All three layers, deliberately. Layer 3 (DB role)
is what I'd point to if forced to pick one — it fails closed even against a
bug in my own Python, a compromised agent process, or a future contributor
routing SQL through some other code path. Layers 1–2 exist because
layer-3-only would mean every mistake surfaces as a raw Postgres permission
error instead of a helpful message the model can react to, and because
layer 2's row cap has no DB-level equivalent worth the complexity here.

## The agentic workflow (plan → act → observe → repeat)

`agent/app/graph.py` builds the agent on LangGraph's prebuilt
`create_react_agent`, which already *is* the loop the brief asks for: call
the model → if it requested tools, run them and feed the results back as
observations → repeat until the model responds without requesting a tool.
Two things make this project-specific:

- **Runtime schema discovery, not hard-coded tables.** Nowhere in
  `agent/` does a table or column name appear. The system prompt explicitly
  requires calling `list_tables` + `describe_schema` before writing SQL, and
  requires re-checking the schema for *every* table used in a JOIN — a
  cheaper model (see below) will otherwise partially explore and guess.
- **Error recovery comes from `langchain-mcp-adapters`, not custom retry
  code.** `MultiServerMCPClient(..., handle_tool_errors=True)`
  (`agent/app/mcp_client.py`) turns an MCP `isError=True` result — a bad
  column name, a syntax error, a guardrail rejection — into a normal
  `ToolMessage(status="error")` instead of raising. The model reads that
  message on its next turn and corrects itself. No `except`/retry loop was
  hand-written for this; it's a property of the MCP error-surfacing contract
  plus the ReAct loop already re-entering the model after every tool call.
- **`ask_clarification`** is a fourth, local (non-MCP) tool. The prompt
  instructs the model to try a case-insensitive partial match first (e.g. a
  literal "Project Atlas" doesn't exist, but `ILIKE '%Atlas%'` finds
  "Atlas"), and only call `ask_clarification` — listing the real candidates
  it found via a query — if that still doesn't resolve. Because the graph
  uses a `MemorySaver` checkpointer keyed by `thread_id`
  (`agent/app/api.py` / `graph.py`), a second `/ask` call with the same
  `thread_id` resumes the same message history — the model doesn't need to
  re-discover the schema after the user answers its question.
- **Recursion / cost guardrail on the agent loop itself**: `recursion_limit`
  (default 24, `AGENT_RECURSION_LIMIT` env var) bounds how many plan/act
  cycles one question can take; hitting it returns a graceful "couldn't
  reach an answer" message instead of running forever.
- **Production-safety odds and ends**: `ChatOpenAI(max_retries=5, timeout=...)`
  plus an outer `tenacity` retry in `api.py` for transient
  `APIConnectionError`/`RateLimitError`/`InternalServerError` (not for
  guardrail rejections or bad SQL — those are handled *inside* the loop, by
  design, not retried blindly outside it); `psycopg_pool` with a startup
  retry (`tenacity`) in the MCP server so a slow-starting Postgres container
  doesn't crash it; a connection pool instead of one connection per call.

## Judgment calls

**Where does safety live?** Defense in depth across all three levels above —
see that section for the full argument. If I had to rank them, DB-level >
MCP-tool-level > prompt-level, but I built all three because each catches a
different failure mode (a parser edge case, a future code path that
bypasses the MCP tool, a model that ignores instructions).

**How much schema does the LLM see?** On-demand introspection
(`list_tables`/`describe_schema`), not the full schema dumped into the
system prompt. Trade-off: this costs extra round-trips (and, as observed
below, a smaller model sometimes doesn't fully explore before guessing), but
it (a) keeps the fixed prompt token cost near zero regardless of how large
the real schema is, (b) generalizes to a database this code has never seen
without editing a single prompt string, and (c) is *why* nothing in
`agent/` needs to change if a column gets renamed — the enforced behavior
("call describe_schema before writing SQL") self-heals against schema
drift, where a baked-in schema-in-the-prompt approach would silently produce
wrong SQL. For a small, fixed schema, dumping it into the prompt would be
cheaper per call and more reliable with a small model; I chose the more
general approach because the brief explicitly asks for runtime discovery.

**Model choice.** Configurable via `OPENAI_MODEL` (default `gpt-4o-mini`) —
deliberately the cheapest tool-calling-capable OpenAI model, per this
project's budget constraint. Observed trade-off during testing: it reliably
gets simple, single-join questions right immediately; on the harder
three-table JOIN example it sometimes needs several extra self-correction
rounds (retrying a column choice, checking `SELECT DISTINCT` on more than
one candidate column) before landing on the right query — but it does land
on it, without ever needing a code change, because the guardrail/error-
recovery/prompt design is what does the correcting, not a bigger model. A
stronger model (e.g. swap `OPENAI_MODEL`, or point `graph.py` at a different
provider) would need fewer of those rounds for the same correctness.

## MCP as a connector / abstraction layer — why not raw SQL or a connection string

The alternative designs this avoids:

- **Giving the LLM a raw connection string.** The model (or a prompt
  injection hidden in a ticket title, a comment body, anything it reads)
  would then be one crafted response away from `psycopg2.connect(...)` and
  arbitrary SQL — DROP, mass DELETE, `pg_read_file`, etc. There is no
  boundary left to enforce; "be careful" is the entire security model.
- **Letting the LLM emit arbitrary SQL that some other code blindly execs.**
  Marginally better (at least the DB layer could apply grants), but the
  read-only/row-cap/statement-timeout logic ends up duplicated at every call
  site that touches the DB, and there's no single place to audit or change
  it.

MCP fixes this by turning "access to a database" into "access to a small,
fixed set of named, typed, independently-implemented tools". Concretely,
that buys three things this project leans on directly:

1. **A capability boundary, not a credential.** The agent process holds an
   HTTP URL, not a password. Even a fully compromised or adversarially-
   prompted agent can only ever call `list_tables`/`describe_schema`/
   `run_query` — the *set of possible actions* is fixed by the server, not
   by whatever the model decides to type. This is the same principle as
   giving a contractor a scoped API key instead of your root password.
2. **A single enforcement point.** All three guardrail layers live in one
   process (`mcp_server/`) that every caller — this agent, a different
   agent, a human debugging with an MCP inspector — goes through identically.
   Compare to raw-SQL-execution-scattered-across-callers, where each call
   site could independently forget to cap rows or check for writes.
3. **A structured, error-recoverable contract**, not a stdout blob. MCP's
   `CallToolResult(isError=True/False, content=[...])` is what lets a failed
   query become a normal, model-readable observation (`ToolMessage(status=
   "error")` via `langchain-mcp-adapters`) instead of an unhandled exception
   that crashes the run or a bare string the model has to guess the meaning
   of. The plan → act → observe loop in this project *is* this contract —
   there's no separate "if error, retry" code because the error already
   arrives in the same shape as a successful result.

In short: MCP isn't "a way to let an LLM talk to a database" so much as "a
way to *not* let an LLM talk to a database" — it talks to a narrow, audited,
self-describing tool surface instead, and the database is an implementation
detail behind it that could be swapped for MySQL, an internal REST API, or a
CSV file without the agent code changing at all.

## Repo layout

```
db/init/                  schema, seed data, read-only role creation
mcp_server/               FastMCP server: list_tables, describe_schema, run_query
agent/app/                config, MCP client adapter, LangGraph agent, FastAPI app
agent/demo.py             guardrail smoke test + both required example questions +
                          clarification round-trip + a harder JOIN example
docker-compose.yml        db, mcp-server, agent-api — three containers, one network
.env.example              all required secrets, none committed
```
