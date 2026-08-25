"""Aplicação Streamable HTTP com superfície mínima e proteções locais."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .mcp_server import create_server
from .repository import Repository
from .snapshot import validate_snapshot

LOGGER = logging.getLogger("matrusp_mcp.http")


class RateLimiter:
    def __init__(self, capacity: float = 20, refill_per_second: float = 1) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str, cost: float = 1) -> bool:
        now = time.monotonic()
        tokens, previous = self._buckets.get(key, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - previous) * self.refill_per_second)
        if tokens < cost:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - cost, now)
        return True


def _headers(scope: dict[str, Any]) -> dict[str, str]:
    return {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}


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


class HostOriginMiddleware:
    """Reject untrusted Host/Origin headers on every exposed HTTP route."""

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        allowed_hosts: tuple[str, ...],
        allowed_origins: tuple[str, ...],
    ) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts
        self.allowed_origins = allowed_origins

    @staticmethod
    def _matches(value: str, allowed: tuple[str, ...]) -> bool:
        if not allowed:
            return False
        return any(
            value == item
            or (item.endswith(":*") and value.split(":", 1)[0] == item[:-2])
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
        if not self._matches(host, tuple(value.lower() for value in self.allowed_hosts)):
            await BodyLimitMiddleware._reject(send, 421, "untrusted host")
            return
        origin = headers.get("origin")
        if origin and not self._matches(origin, self.allowed_origins):
            await BodyLimitMiddleware._reject(send, 403, "untrusted origin")
            return
        await self.app(scope, receive, send)


class RateLimitMiddleware:
    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        trusted_proxy_cidrs: tuple[str, ...] = (),
        *,
        snapshot_id: str = "unknown",
    ) -> None:
        self.app = app
        self.limiter = RateLimiter()
        self.trusted = tuple(ipaddress.ip_network(value) for value in trusted_proxy_cidrs)
        self.global_concurrency = asyncio.Semaphore(16)
        self.generation_concurrency = asyncio.Semaphore(4)
        self.snapshot_id = snapshot_id
        self.aggregate: dict[str, int] = {"requests": 0, "accepted": 0, "rejected": 0}

    def _client_ip(self, scope: dict[str, Any]) -> str:
        direct = str((scope.get("client") or ("0.0.0.0", 0))[0])
        try:
            trusted = any(ipaddress.ip_address(direct) in network for network in self.trusted)
        except ValueError:
            trusted = False
        if trusted:
            forwarded = _headers(scope).get("x-forwarded-for", "").split(",")
            if forwarded and forwarded[0].strip():
                return forwarded[0].strip()
        return direct

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[..., Awaitable[None]],
    ) -> None:
        if (
            scope.get("type") != "http"
            or scope.get("path") != "/mcp"
            or scope.get("method") != "POST"
        ):
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        request_id = secrets.token_hex(8)
        message = await receive()
        chunks = [message.get("body", b"")]
        while message.get("more_body", False):
            message = await receive()
            chunks.append(message.get("body", b""))
        body = b"".join(chunks)
        try:
            payload = json.loads(body or b"{}")
            name = str(payload.get("params", {}).get("name", ""))
        except (ValueError, TypeError, AttributeError):
            name = ""
        cost = (
            5
            if name == "generate_schedules"
            else 2
            if name in {"find_gap_fillers", "check_schedule_conflicts", "compare_schedules"}
            else 1
        )
        self.aggregate["requests"] += 1
        if not self.limiter.allow(self._client_ip(scope), cost):
            self.aggregate["rejected"] += 1
            LOGGER.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "tool": name or None,
                        "duration_ms": round((time.monotonic() - started) * 1000, 3),
                        "status": 429,
                        "snapshot_id": self.snapshot_id,
                        "counters": dict(self.aggregate),
                    },
                    sort_keys=True,
                )
            )
            await BodyLimitMiddleware._reject(send, 429, "rate limit exceeded")
            return
        consumed = False

        async def replay() -> dict[str, Any]:
            nonlocal consumed
            if consumed:
                return {"type": "http.request", "body": b"", "more_body": False}
            consumed = True
            return {"type": "http.request", "body": body, "more_body": False}

        async with self.global_concurrency:
            self.aggregate["accepted"] += 1
            status_code = 200

            async def capture(message: dict[str, Any]) -> None:
                nonlocal status_code
                if message.get("type") == "http.response.start":
                    status_code = int(message.get("status", 200))
                await send(message)

            if name == "generate_schedules":
                async with self.generation_concurrency:
                    await self.app(scope, replay, capture)
            else:
                await self.app(scope, replay, capture)
        LOGGER.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "tool": name or None,
                    "duration_ms": round((time.monotonic() - started) * 1000, 3),
                    "status": status_code,
                    "snapshot_id": self.snapshot_id,
                    "counters": dict(self.aggregate),
                },
                sort_keys=True,
            )
        )


def create_http_app(
    snapshot_path: Path,
    *,
    allowed_hosts: tuple[str, ...] = (),
    allowed_origins: tuple[str, ...] = (),
    trusted_proxy_cidrs: tuple[str, ...] = (),
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
    app = RateLimitMiddleware(
        app,
        trusted_proxy_cidrs,
        snapshot_id=repository.snapshot_id,
    )
    app = BodyLimitMiddleware(app)
    app = HostOriginMiddleware(app, tuple(hosts), tuple(allowed_origins))
    return app
