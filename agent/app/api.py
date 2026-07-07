import logging
import uuid

import openai
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.graph import ask

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent.api")

app = FastAPI(title="Delivery Tracker Agentic Retrieval")


class AskRequest(BaseModel):
    question: str
    thread_id: str | None = None


class TraceStep(BaseModel):
    step: str
    tool: str
    args: dict | None = None
    status: str | None = None
    result: str | None = None


class AskResponse(BaseModel):
    answer: str
    thread_id: str
    trace: list[dict]


# Transient failures only (rate limits, overloaded, connection resets) — a
# guardrail rejection or a bad-SQL error is *not* retried here, it's handled
# inside the agent loop itself by feeding the error back to the model.
_TRANSIENT_OPENAI_ERRORS = (
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)


@retry(
    retry=retry_if_exception_type(_TRANSIENT_OPENAI_ERRORS),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    stop=stop_after_attempt(4),
    reraise=True,
)
async def _ask_with_retry(question: str, thread_id: str):
    return await ask(question, thread_id)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
async def ask_endpoint(req: AskRequest) -> AskResponse:
    thread_id = req.thread_id or str(uuid.uuid4())
    try:
        result = await _ask_with_retry(req.question, thread_id)
    except _TRANSIENT_OPENAI_ERRORS as exc:
        logger.exception("Upstream LLM provider error after retries")
        raise HTTPException(status_code=502, detail=f"LLM provider error: {exc}") from exc
    return AskResponse(answer=result.answer, thread_id=result.thread_id, trace=result.trace)
