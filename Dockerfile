FROM python:3.12-slim

LABEL org.opencontainers.image.title="matrusp-mcp" \
      org.opencontainers.image.description="Read-only MCP server for public USP JupiterWeb snapshots" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.source="https://github.com/matrusp/matrusp-mcp"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MATRUSP_SNAPSHOT=/app/data/matrusp.sqlite

WORKDIR /app
COPY pyproject.toml README.md LICENSE CONTRIBUTORS.md ./
COPY src ./src
COPY data/matrusp.sqlite ./data/matrusp.sqlite
RUN pip install --no-cache-dir . \
    && python -m matrusp_mcp.cli validate /app/data/matrusp.sqlite

RUN addgroup --system --gid 10001 matrusp \
    && adduser --system --uid 10001 --ingroup matrusp matrusp \
    && chown -R matrusp:matrusp /app
USER 10001:10001

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz').read()"
ENTRYPOINT ["matrusp-mcp"]
CMD ["serve", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
