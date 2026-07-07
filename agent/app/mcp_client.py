"""The only place in this codebase that knows an MCP server exists.

The agent never opens a database connection and holds no DB credentials —
it discovers and calls tools (list_tables / describe_schema / run_query)
exposed over MCP by a separate process (see mcp_server/). This module is
the thin adapter that turns those MCP tools into LangChain tools the
LangGraph agent can bind to a model.
"""

import logging

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger("agent.mcp_client")

_client = MultiServerMCPClient(
    {
        "delivery_tracker": {
            "url": settings.mcp_server_url,
            "transport": "streamable_http",
        }
    },
    # An MCP tool execution error (isError=True, e.g. a bad-column SQL error
    # or a guardrail rejection) is returned to the model as a failed
    # ToolMessage instead of raising — this is what lets the plan/act/observe
    # loop self-correct instead of crashing the run.
    handle_tool_errors=True,
)


@retry(
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    reraise=True,
)
async def get_mcp_tools() -> list[BaseTool]:
    """Discover tools from the MCP server, retrying while it is still starting up."""
    tools = await _client.get_tools()
    logger.info("Loaded %d MCP tools: %s", len(tools), [t.name for t in tools])
    return tools
