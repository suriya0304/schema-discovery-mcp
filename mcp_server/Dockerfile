FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py guardrails.py server.py ./

# Runs as a non-root user; this process never has write access to the DB
# regardless (see mcp_reader role), but least privilege applies here too.
RUN useradd --create-home --uid 1000 mcp
USER mcp

EXPOSE 8000

CMD ["python", "server.py"]
