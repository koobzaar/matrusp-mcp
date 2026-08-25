from pathlib import Path
from typing import Any

import httpx
import pytest

from matrusp_mcp.http_server import (
    BodyLimitMiddleware,
    HostOriginMiddleware,
    RateLimiter,
    create_http_app,
)
from matrusp_mcp.snapshot import build_snapshot

from .test_snapshot_repository import sample_data


@pytest.mark.asyncio
async def test_health_readiness_and_route_surface(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.sqlite"
    build_snapshot(sample_data(), snapshot)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_http_app(snapshot)), base_url="http://testserver"
    ) as client:
        assert (await client.get("/healthz")).json()["status"] == "ok"
        ready = await client.get("/readyz")
        assert ready.status_code == 200 and ready.json()["ready"] is True
        assert (await client.get("/")).status_code == 404


def test_body_limit_is_256_kib_and_rate_limiter_uses_weighted_tokens() -> None:
    limiter = RateLimiter(capacity=20, refill_per_second=1)
    assert all(limiter.allow("127.0.0.1", 1) for _ in range(20))
    assert limiter.allow("127.0.0.1", 1) is False
    assert limiter.allow("127.0.0.2", 5) is True


def http_scope(*headers: tuple[bytes, bytes]) -> dict[str, Any]:
    return {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": list(headers),
        "client": ("127.0.0.1", 1234),
    }


async def append_message(target: list[dict[str, Any]], message: dict[str, Any]) -> None:
    target.append(message)


@pytest.mark.asyncio
@pytest.mark.parametrize("length", (b"5", b"999999"))
async def test_declared_oversized_bodies_are_rejected_without_being_read(length: bytes) -> None:
    received = 0

    async def receive() -> dict[str, Any]:
        nonlocal received
        received += 1
        raise AssertionError("oversized declared body must not be consumed")

    sent: list[dict[str, Any]] = []

    async def downstream(*args: Any) -> None:
        raise AssertionError("oversized request must not reach the app")

    app = BodyLimitMiddleware(downstream, maximum=4)
    await app(
        http_scope((b"content-length", length)),
        receive,
        lambda message: append_message(sent, message),
    )
    assert received == 0
    assert sent[0]["status"] == 413


@pytest.mark.asyncio
@pytest.mark.parametrize("length", (b"invalid", b"-1"))
async def test_invalid_content_lengths_are_rejected_without_being_read(length: bytes) -> None:
    received = 0

    async def receive() -> dict[str, Any]:
        nonlocal received
        received += 1
        return {"type": "http.request", "body": b"", "more_body": False}

    sent: list[dict[str, Any]] = []

    async def downstream(*args: Any) -> None:
        raise AssertionError("invalid request must not reach the app")

    await BodyLimitMiddleware(downstream, maximum=4)(
        http_scope((b"content-length", length)),
        receive,
        lambda message: append_message(sent, message),
    )
    assert received == 0
    assert sent[0]["status"] == 400


@pytest.mark.asyncio
async def test_chunked_body_stops_being_read_as_soon_as_it_crosses_the_limit() -> None:
    messages = [
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"de", "more_body": True},
        {"type": "http.request", "body": b"must-not-be-read", "more_body": False},
    ]
    received = 0

    async def receive() -> dict[str, Any]:
        nonlocal received
        message = messages[received]
        received += 1
        return message

    sent: list[dict[str, Any]] = []

    async def downstream(*args: Any) -> None:
        raise AssertionError("oversized request must not reach the app")

    await BodyLimitMiddleware(downstream, maximum=4)(
        http_scope(), receive, lambda message: append_message(sent, message)
    )
    assert received == 2
    assert sent[0]["status"] == 413


@pytest.mark.asyncio
async def test_untrusted_host_is_rejected_before_body_validation_or_consumption() -> None:
    received = 0

    async def receive() -> dict[str, Any]:
        nonlocal received
        received += 1
        raise AssertionError("untrusted host body must not be consumed")

    sent: list[dict[str, Any]] = []

    async def downstream(*args: Any) -> None:
        raise AssertionError("untrusted host must not reach the app")

    app = HostOriginMiddleware(
        BodyLimitMiddleware(downstream, maximum=4), ("trusted.test",), ()
    )
    await app(
        http_scope((b"host", b"evil.test"), (b"content-length", b"999999")),
        receive,
        lambda message: append_message(sent, message),
    )
    assert received == 0
    assert sent[0]["status"] == 421


@pytest.mark.asyncio
async def test_normal_body_is_replayed_once_to_the_application() -> None:
    messages = [
        {"type": "http.request", "body": b"ab", "more_body": True},
        {"type": "http.request", "body": b"cd", "more_body": False},
    ]

    async def receive() -> dict[str, Any]:
        return messages.pop(0)

    seen: list[dict[str, Any]] = []
    sent: list[dict[str, Any]] = []

    async def downstream(
        scope: dict[str, Any], receive_body: Any, send: Any
    ) -> None:
        del scope
        seen.append(await receive_body())
        seen.append(await receive_body())
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = HostOriginMiddleware(
        BodyLimitMiddleware(downstream, maximum=4), ("trusted.test",), ()
    )
    await app(
        http_scope((b"host", b"trusted.test"), (b"content-length", b"4")),
        receive,
        lambda message: append_message(sent, message),
    )
    assert seen == [
        {"type": "http.request", "body": b"abcd", "more_body": False},
        {"type": "http.request", "body": b"", "more_body": False},
    ]
    assert sent[0]["status"] == 204
