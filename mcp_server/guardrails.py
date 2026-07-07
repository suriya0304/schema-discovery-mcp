"""App-level read-only guardrail.

This is layer 1 of defense in depth. Layer 2 is the `mcp_reader` Postgres role
itself, which has `default_transaction_read_only = on` and only ever had
SELECT granted to it (see db/init/03_readonly_role.sh) — so even a bug here
cannot produce a write. See README "Where does safety live?" for the full
argument.
"""

import re

import sqlparse
from sqlparse.tokens import DDL, DML, Keyword

_FORBIDDEN_STATEMENT_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "CREATE",
    "MERGE",
    "CALL",
    "COPY",
    "VACUUM",
    "EXECUTE",
    "DO",
    "REINDEX",
    "REFRESH",
}

# Belt-and-suspenders textual scan in case a keyword shows up in a place
# sqlparse's tokenizer doesn't classify as DDL/DML (e.g. inside a CTE).
_FORBIDDEN_PATTERN = re.compile(
    r"\b(" + "|".join(_FORBIDDEN_STATEMENT_KEYWORDS) + r")\b", re.IGNORECASE
)


class GuardrailViolation(ValueError):
    """Raised when a query fails the read-only or single-statement check."""


def enforce_read_only_select(sql: str) -> str:
    """Validate that `sql` is a single, read-only SELECT/CTE statement.

    Returns the query re-wrapped so a row cap always applies, regardless of
    whether the model included its own LIMIT.

    Raises:
        GuardrailViolation: if the query is empty, contains more than one
            statement, or contains any write/DDL keyword.
    """
    cleaned = sqlparse.format(sql, strip_comments=True).strip()
    if not cleaned:
        raise GuardrailViolation("Empty query.")

    statements = [s for s in sqlparse.parse(cleaned) if s.tokens]
    if len(statements) != 1:
        raise GuardrailViolation(
            "Only a single SELECT statement is allowed per call "
            f"(found {len(statements)})."
        )

    statement = statements[0]
    first_meaningful = next(
        (t for t in statement.tokens if not t.is_whitespace), None
    )
    if first_meaningful is None or first_meaningful.ttype not in (DML, Keyword.CTE):
        raise GuardrailViolation(
            "Only SELECT (or WITH ... SELECT) statements are permitted."
        )
    if first_meaningful.ttype is DML and first_meaningful.normalized.upper() != "SELECT":
        raise GuardrailViolation("Only SELECT statements are permitted.")

    for token in statement.flatten():
        if token.ttype in (DDL,) or (
            token.ttype is Keyword and token.normalized.upper() in _FORBIDDEN_STATEMENT_KEYWORDS
        ):
            raise GuardrailViolation(
                f"Statement contains a disallowed keyword: {token.normalized.upper()}."
            )

    if _FORBIDDEN_PATTERN.search(cleaned):
        raise GuardrailViolation("Statement contains a disallowed keyword.")

    if cleaned.rstrip(";").count(";") > 0:
        raise GuardrailViolation("Multiple statements separated by ';' are not allowed.")

    return cleaned.rstrip(";")


def cap_rows(sql: str, row_limit: int) -> str:
    """Wrap the query so Postgres never returns more than `row_limit` rows.

    Wrapping as a subquery (rather than regex-inserting LIMIT) works whether
    or not the caller's query already has its own LIMIT/ORDER BY/CTE.
    """
    return f"SELECT * FROM ({sql}) AS _guarded_subquery LIMIT {row_limit}"
