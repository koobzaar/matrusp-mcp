"""Aplicação Streamable HTTP com superfície mínima e proteções locais."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .mcp_server import create_server
from .repository import Repository
from .snapshot import validate_snapshot


def _headers(scope: dict[str, Any]) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


class BodyLimitMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]], maximum: int = 256 * 1024) -> None:
        self.app, self.maximum = app, maximum

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[..., Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        try:
            declared_length = int(headers.get("content-length", "0") or "0")
        except ValueError:
            await self._reject(send, 400, "invalid content length")
            return
        if declared_length < 0:
            await self._reject(send, 400, "invalid content length")
            return
        if declared_length > self.maximum:
            await self._reject(send, 413, "request body too large")
            return
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.maximum:
                await self._reject(send, 413, "request body too large")
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        sent = False

        async def replay() -> dict[str, Any]:
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": b"".join(chunks), "more_body": False}

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send: Callable[..., Awaitable[None]], status: int, detail: str) -> None:
        body = json.dumps({"error": detail}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class MCPMethodMiddleware:
    """Keep the stateless JSON endpoint finite when a client probes GET /mcp."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[..., Awaitable[None]],
    ) -> None:
        if (
            scope.get("type") == "http"
            and scope.get("path") == "/mcp"
            and scope.get("method") == "GET"
        ):
            body = json.dumps({"error": "method not allowed"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 405,
                    "headers": [
                        (b"allow", b"POST"),
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


class HostOriginMiddleware:
    """Reject untrusted Host/Origin headers on every exposed HTTP route."""

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        allowed_hosts: tuple[str, ...],
        allowed_origins: tuple[str, ...],
    ) -> None:
        self.app = app
        self.allowed_hosts = tuple(value.lower() for value in allowed_hosts)
        self.allowed_origins = tuple(value.lower() for value in allowed_origins)

    @staticmethod
    def _matches(value: str, allowed: tuple[str, ...]) -> bool:
        if not allowed:
            return False
        return any(
            value == item
            or (item.endswith(":*") and value.startswith(item[:-2] + ":"))
            for item in allowed
        )

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[..., Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        host = headers.get("host", "").lower()
        if not self._matches(host, self.allowed_hosts):
            await BodyLimitMiddleware._reject(send, 421, "untrusted host")
            return
        origin = headers.get("origin")
        if origin and not self._matches(origin.lower(), self.allowed_origins):
            await BodyLimitMiddleware._reject(send, 403, "untrusted origin")
            return
        await self.app(scope, receive, send)


def create_http_app(
    snapshot_path: Path,
    *,
    allowed_hosts: tuple[str, ...] = (),
    allowed_origins: tuple[str, ...] = (),
) -> Any:
    path = Path(snapshot_path).resolve()
    repository = Repository(path)
    server = create_server(path)
    hosts = list(allowed_hosts) or [
        "localhost",
        "localhost:*",
        "127.0.0.1",
        "127.0.0.1:*",
        "testserver",
        "testserver:*",
    ]
    security = TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=list(allowed_origins))

    @server.custom_route("/healthz", methods=["GET"])
    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok", "snapshot_id": repository.snapshot_id})

    @server.custom_route("/readyz", methods=["GET"])
    async def ready(_: Request) -> Response:
        report = validate_snapshot(path)
        return JSONResponse(
            {
                "ready": report.ok,
                "snapshot_id": repository.snapshot_id,
                "counts": report.counts,
                "errors": report.errors,
            },
            status_code=200 if report.ok else 503,
        )

    app = server.streamable_http_app(
        # JSON responses keep the stateless endpoint finite for ordinary
        # request/response clients while remaining a conforming Streamable
        # HTTP transport (clients may still advertise the SSE media type).
        json_response=True,
        max_request_body_size=256 * 1024,
        stateless_http=True,
        transport_security=security,
    )
    app = BodyLimitMiddleware(app)
    app = MCPMethodMiddleware(app)
    app = HostOriginMiddleware(app, tuple(hosts), tuple(allowed_origins))
    return app
