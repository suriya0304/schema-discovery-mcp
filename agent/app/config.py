from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Agent-side configuration.

    Note what is deliberately absent: no PG_HOST / PG_USER / PG_PASSWORD here.
    This process has no notion of the database's existence beyond "there is an
    MCP server at mcp_server_url that exposes some tools" — it cannot connect
    to Postgres even if it wanted to.
    """

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    openai_api_key: str
    # Cheap, tool-calling-capable model by default to keep per-call cost low.
    openai_model: str = "gpt-4o-mini"

    mcp_server_url: str = "http://mcp-server:8000/mcp"

    agent_recursion_limit: int = 24
    request_timeout_s: int = 60


settings = Settings()
