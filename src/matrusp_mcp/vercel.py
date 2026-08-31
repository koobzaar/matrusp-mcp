"""Vercel-specific environment adaptation for the shared HTTP application."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .http_server import create_http_app

_VERCEL_HOST_VARIABLES = (
    "VERCEL_URL",
    "VERCEL_BRANCH_URL",
    "VERCEL_PROJECT_PRODUCTION_URL",
)


def _csv(environment: Mapping[str, str], name: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in environment.get(name, "").split(",") if value.strip())


def _allowed_hosts(environment: Mapping[str, str]) -> tuple[str, ...]:
    configured = _csv(environment, "MATRUSP_ALLOWED_HOSTS")
    vercel = tuple(
        value
        for name in _VERCEL_HOST_VARIABLES
        if (value := environment.get(name, "").strip())
    )
    return tuple(dict.fromkeys((*configured, *vercel)))


def create_vercel_app(
    project_root: Path,
    environment: Mapping[str, str] | None = None,
) -> Any:
    """Create the ASGI app using the immutable bundled snapshot and Vercel domains."""
    values = os.environ if environment is None else environment
    snapshot = Path(values.get("MATRUSP_SNAPSHOT", "data/matrusp.sqlite"))
    if not snapshot.is_absolute():
        snapshot = project_root / snapshot
    return create_http_app(
        snapshot,
        allowed_hosts=_allowed_hosts(values),
        allowed_origins=_csv(values, "MATRUSP_ALLOWED_ORIGINS"),
    )
