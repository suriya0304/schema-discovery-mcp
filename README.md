# MCP Database Agent

An agentic database question-answering system built with the **Model Context Protocol (MCP)**.

The project consists of three Dockerized services:

- **PostgreSQL** — Stores the application data.
- **MCP Server** — Exposes database capabilities through MCP.
- **React Agent API** — Uses an OpenAI LLM and MCP tools to answer natural language questions about the database.

The LLM never connects to the database directly. All database access happens through MCP tools.

---

## Services

| Service | Description |
|---------|-------------|
| `db` | PostgreSQL database with persistent Docker volume |
| `mcp-server` | MCP server exposing database tools |
| `react-agent` | AI agent powered by OpenAI + MCP |

---

## MCP Tools

The MCP server exposes the following tools:

| Tool | Description |
|------|-------------|
| `run_query` | Executes read-only SQL queries |
| `describe_schema` | Returns schema information |
| `list_tables` | Lists available database tables |

The React Agent also includes an additional tool:

| Tool | Description |
|------|-------------|
| `ask_user` | Requests clarification when the user's question is ambiguous |

---

## Configuration

Create a `.env` file:

```env
OPENAI_API_KEY=your_openai_api_key

POSTGRES_USER=app_admin
POSTGRES_PASSWORD=your_password
POSTGRES_DB=delivery_tracker
```

---

## Running

Start all services:

```bash
docker compose up --build
```

Run in background:

```bash
docker compose up -d --build
```

Stop:

```bash
docker compose down
```

To remove volumes:

```bash
docker compose down -v
```

---

## API

### Ask a Question

```http
POST /ask/
```

Example:

```bash
curl --location 'http://localhost:8080/ask/' \
--header 'Content-Type: application/json' \
--data '{
    "thread_id": "test3",
    "question": "which initiatives are currently shipped?"
}'
```

Example request:

```json
{
  "thread_id": "test3",
  "question": "which initiatives are currently shipped?"
}
```

---

## Conversation Support

The agent maintains conversation state using the supplied `thread_id`.

Reusing the same `thread_id` allows follow-up questions without repeating previous context.

Example:

```text
User: List all tables.

User: Which one stores tickets?

User: Show only open ones.
```

---

## Project Structure

```text
.
├── docker-compose.yml
├── db/
│   ├── init/
│   └── data/
├── mcp-server/
├── react-agent/
└── README.md
```

---

## Design

- Dockerized microservice architecture
- MCP-based database access
- No database credentials exposed to the LLM
- Read-only database operations
- Multi-turn conversations via `thread_id`
- Tool-based reasoning with clarification support
