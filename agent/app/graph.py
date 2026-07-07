"""Plan -> act -> observe agent, built on langgraph's prebuilt ReAct executor.

Why the prebuilt executor rather than a hand-rolled loop: `create_react_agent`
already implements exactly the loop this assessment asks for (call model ->
if it requested tools, run them and feed results back -> repeat until the
model answers without requesting a tool), and `MultiServerMCPClient`'s
`handle_tool_errors=True` (see mcp_client.py) turns a failed run_query call
into a normal `ToolMessage(status="error")` instead of an exception. So a bad
SQL query doesn't crash the graph — it becomes an observation the model reads
on the next loop iteration and reacts to, which is the "error recovery"
requirement. What we add on top: a system prompt that forces runtime schema
discovery (no hard-coded table/column names anywhere in this file), a local
`ask_clarification` tool for genuinely ambiguous questions, and a checkpointer
so a clarification round-trip can resume the same reasoning thread.
"""

import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent

from app.config import settings
from app.mcp_client import get_mcp_tools

logger = logging.getLogger("agent.graph")

SYSTEM_PROMPT = """\
You are a careful data analyst answering questions about a company's \
delivery-tracker database, which you can only access through the tools \
provided (list_tables, describe_schema, run_query, ask_clarification).

Rules:
1. Never assume a table or column name. Call list_tables once, then call \
   describe_schema separately for *every single table* you intend to \
   reference in your query (every table in a JOIN, not just one or two of \
   them) before writing any SQL. The schema may differ from what the \
   question's wording suggests (e.g. a "department" in the question may \
   correspond to a differently-named column, and a "project" may be named \
   something else entirely) — do not guess a column name (e.g. "title" vs \
   "name") for a table you have not described.
2. Only ever write a single read-only SELECT (CTEs with WITH are fine). You \
   cannot write, and should not attempt to write, INSERT/UPDATE/DELETE/DDL — \
   the tool will reject it.
3. If run_query returns an error, read the error message carefully, re-check \
   the schema if needed, and retry with a corrected query. Do not give up \
   after one failure, and do not repeat the exact same failing query.
4. If the question references a specific name (a project, a team, a person) \
   and an exact-string filter on it returns zero rows, do NOT immediately \
   conclude it doesn't exist. First retry with a case-insensitive partial \
   match (e.g. `ILIKE '%core_word%'`, stripping generic wrapper words like \
   "Project"/"Team"/"the" — search for "Atlas" rather than "Project Atlas"). \
   Only if that also finds nothing (or finds several equally plausible \
   candidates) should you call ask_clarification with whatever close \
   candidates you found, and stop — do not call any more tools after that.
5. Ground your final answer strictly in what the queries returned. Cite the \
   concrete values (names, statuses, counts) you found. If a query returned \
   zero rows after the ILIKE retry in rule 4, say so plainly instead of \
   inventing an answer.
6. Before finalizing a query, re-read the original question and confirm every \
   condition it implies (a named project/team/person, a status, a category) \
   is actually present in your WHERE clause — it is easy to drop one while \
   iterating.
7. When a table has more than one text column that could plausibly hold the \
   category/name term used in the question (e.g. both a proper "name" and a \
   separate category/area/type column), you MUST run one \
   `SELECT DISTINCT <candidate_column> FROM <table>` for EACH plausible \
   candidate column (not just the first/most obvious one) and see which one \
   actually contains the term the question used, before writing your final \
   filtering query. If your first candidate column comes back with no match, \
   you MUST try the next candidate column on that same table before giving \
   up or asking for clarification — do not stop after checking only one \
   column.
8. A zero-row result is a signal to double check you used the right column \
   and exact value (per rule 7) — do not simply report "none found" without \
   that check.
9. Be concise. A few sentences plus, if useful, a short list, is enough.
"""


@tool
def ask_clarification(question: str) -> str:
    """Ask the user a clarifying question when the request is ambiguous.

    Use this only after you've queried the database and confirmed there is a
    genuine ambiguity (e.g. no exact name match, or multiple plausible
    matches). Pass the exact question to show the user, ideally listing the
    candidates you found. After calling this, stop — do not call any other
    tool in this turn; your final response should be this question.
    """
    return question


def _build_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        timeout=settings.request_timeout_s,
        max_retries=5,  # transient 5xx/rate-limit errors from the OpenAI API
        temperature=0,
    )


_checkpointer = MemorySaver()
_agent = None


async def _get_agent():
    global _agent
    if _agent is None:
        mcp_tools = await get_mcp_tools()
        all_tools = [*mcp_tools, ask_clarification]
        _agent = create_react_agent(
            model=_build_model(),
            tools=all_tools,
            prompt=SYSTEM_PROMPT,
            checkpointer=_checkpointer,
        )
    return _agent


class AgentAnswer:
    def __init__(self, answer: str, trace: list[dict], thread_id: str):
        self.answer = answer
        self.trace = trace
        self.thread_id = thread_id


def _summarize_trace(messages: list[BaseMessage]) -> list[dict]:
    """Turn the raw message list into a compact, demo-friendly trace of
    what the agent actually did: which tools it called, with what
    arguments, and what came back (including errors)."""
    trace = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                trace.append({"step": "act", "tool": call["name"], "args": call["args"]})
        elif msg.type == "tool":
            status = getattr(msg, "status", "success")
            trace.append(
                {
                    "step": "observe",
                    "tool": msg.name,
                    "status": status,
                    "result": str(msg.content)[:800],
                }
            )
    return trace


async def ask(question: str, thread_id: str) -> AgentAnswer:
    """Run one turn of the plan/act/observe loop for `question`.

    `thread_id` scopes conversation memory: calling this again with the same
    thread_id (e.g. after a clarifying question) continues the same
    reasoning thread instead of starting from scratch.
    """
    agent = await _get_agent()
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": settings.agent_recursion_limit}
    try:
        result = await agent.ainvoke({"messages": [HumanMessage(content=question)]}, config=config)
    except GraphRecursionError:
        logger.warning("Agent hit recursion limit for thread %s", thread_id)
        return AgentAnswer(
            answer=(
                "I wasn't able to reach a grounded answer within the allotted "
                "number of steps. Could you narrow down the question?"
            ),
            trace=[],
            thread_id=thread_id,
        )

    messages = result["messages"]
    final = messages[-1]
    return AgentAnswer(answer=final.content, trace=_summarize_trace(messages), thread_id=thread_id)
