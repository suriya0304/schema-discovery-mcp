from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from the environment (see docker-compose.yml).

    Credentials never appear in code or in any prompt seen by the LLM — the
    agent only ever talks to this process over MCP, never to Postgres directly.
    """

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    pg_host: str = "db"
    pg_port: int = 5432
    pg_database: str = "delivery_tracker"
    pg_user: str = "mcp_reader"
    pg_password: str

    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000

    max_rows: int = 200
    statement_timeout_ms: int = 5000

    @property
    def conninfo(self) -> str:
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={self.pg_database} "
            f"user={self.pg_user} password={self.pg_password} "
            f"options='-c statement_timeout={self.statement_timeout_ms}'"
        )


settings = Settings()
