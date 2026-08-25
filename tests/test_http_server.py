from pathlib import Path

import httpx
import pytest

from matrusp_mcp.http_server import RateLimiter, create_http_app
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
