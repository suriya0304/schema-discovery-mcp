"""End-to-end demo of DB access via MCP + the agentic retrieval loop.

Run from the host (after `docker compose up -d`):
    docker compose exec agent-api python demo.py

Or from a machine with the port published, against http://localhost:8080.

Sections:
  1. Guardrail smoke test -- talks to the MCP server directly (no LLM), to
     deterministically prove the read-only / single-statement enforcement
     works, independent of what any model happens to generate.
  2. Simple single-table question, answered through the full agent.
  3. Multi-table JOIN question, answered through the full agent.
  4. A follow-up/clarification round-trip: an ambiguous question, then a
     second call on the same thread_id supplying the missing detail.
  5. A natural-language question chosen to be likely to need a self-correction
     (the trace shows whether the agent's first SQL attempt failed and was
     retried).
"""

import asyncio
import json
import os
import uuid

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8080")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://mcp-server:8000/mcp")


def header(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


async def guardrail_smoke_test() -> None:
    header("1. Guardrail smoke test (direct MCP calls, no LLM involved)")
    async with streamablehttp_client(MCP_SERVER_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("\n-- attempting a write (DELETE) through run_query --")
            result = await session.call_tool("run_query", {"sql": "DELETE FROM tickets"})
            print("isError:", result.isError)
            print(result.content[0].text)
            assert result.isError, "guardrail failed to reject a write!"

            print("\n-- attempting DROP TABLE --")
            result = await session.call_tool("run_query", {"sql": "DROP TABLE tickets"})
            print("isError:", result.isError)
            print(result.content[0].text)
            assert result.isError, "guardrail failed to reject a DROP!"

            print("\n-- a query referencing a column that doesn't exist --")
            result = await session.call_tool(
                "run_query", {"sql": "SELECT department FROM contributors"}
            )
            print("isError:", result.isError)
            print(result.content[0].text)
            assert result.isError

            print("\n-- a normal, valid read, for contrast --")
            result = await session.call_tool(
                "run_query", {"sql": "SELECT full_name FROM contributors LIMIT 2"}
            )
            print("isError:", result.isError)
            print(result.content[0].text)

    print("\nAll guardrail checks behaved as expected.")


def print_trace(trace: list[dict]) -> None:
    if not trace:
        print("(no tool calls recorded)")
        return
    for step in trace:
        if step["step"] == "act":
            print(f"  -> call {step['tool']}({json.dumps(step['args'])})")
        else:
            status = step.get("status", "success")
            marker = "ERROR" if status == "error" else "ok"
            result_preview = step["result"].replace("\n", " ")[:200]
            print(f"     [{marker}] {step['tool']} -> {result_preview}")


async def ask(client: httpx.AsyncClient, question: str, thread_id: str | None = None) -> dict:
    payload = {"question": question}
    if thread_id:
        payload["thread_id"] = thread_id
    resp = await client.post(f"{AGENT_BASE_URL}/ask", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()


async def main() -> None:
    await guardrail_smoke_test()

    async with httpx.AsyncClient() as client:
        header("2. Simple filter: \"Fetch contributor details where department = 'AI'\"")
        result = await ask(client, "Fetch contributor details where department is 'AI'.")
        print("\nAnswer:\n", result["answer"])
        print("\nTrace:")
        print_trace(result["trace"])

        header("3. Multi-table JOIN: \"Which AI-team members have open issues on Project Atlas?\"")
        result = await ask(client, "Which AI-team members have open issues on Project Atlas?")
        print("\nAnswer:\n", result["answer"])
        print("\nTrace:")
        print_trace(result["trace"])

        header("4. Follow-up / clarification round-trip")
        thread_id = str(uuid.uuid4())
        print("Turn 1 -- ambiguous question (no such project exists):")
        result = await ask(client, "Who is working on the Nova project?", thread_id=thread_id)
        print("\nAgent:\n", result["answer"])
        print("\nTrace:")
        print_trace(result["trace"])

        print("\nTurn 2 -- user clarifies, same thread_id:")
        result = await ask(
            client,
            "Sorry, I meant the Atlas initiative.",
            thread_id=thread_id,
        )
        print("\nAgent:\n", result["answer"])
        print("\nTrace:")
        print_trace(result["trace"])

        header("5. Question likely to require a self-corrected query")
        result = await ask(
            client,
            "For each squad's focus area, how many open tickets does it have?",
        )
        print("\nAnswer:\n", result["answer"])
        print("\nTrace:")
        print_trace(result["trace"])

    print("\nDemo complete.")


if __name__ == "__main__":
    asyncio.run(main())
