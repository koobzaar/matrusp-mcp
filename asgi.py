"""ASGI entrypoint discovered by the Vercel Python runtime."""

from pathlib import Path

from matrusp_mcp.vercel import create_vercel_app

app = create_vercel_app(Path(__file__).resolve().parent)
