from pathlib import Path

import httpx
import pytest

from matrusp_mcp.snapshot import build_snapshot
from matrusp_mcp.vercel import create_vercel_app

from .test_snapshot_repository import sample_data


@pytest.mark.asyncio
async def test_vercel_app_uses_platform_and_configured_hosts(tmp_path: Path) -> None:
    snapshot = tmp_path / "data" / "matrusp.sqlite"
    snapshot.parent.mkdir()
    build_snapshot(sample_data(), snapshot)
    app = create_vercel_app(
        tmp_path,
        {
            "VERCEL_URL": "matrusp-deployment.vercel.app",
            "VERCEL_BRANCH_URL": "matrusp-git-main.vercel.app",
            "VERCEL_PROJECT_PRODUCTION_URL": "matrusp.vercel.app",
            "MATRUSP_ALLOWED_HOSTS": "mcp.example.org, matrusp.vercel.app",
        },
    )

    for host in (
        "matrusp-deployment.vercel.app",
        "matrusp-git-main.vercel.app",
        "matrusp.vercel.app",
        "mcp.example.org",
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=f"https://{host}"
        ) as client:
            response = await client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://untrusted.example.org"
    ) as client:
        assert (await client.get("/healthz")).status_code == 421


@pytest.mark.asyncio
async def test_vercel_app_retains_local_defaults_without_host_variables(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.sqlite"
    build_snapshot(sample_data(), snapshot)
    app = create_vercel_app(tmp_path, {"MATRUSP_SNAPSHOT": str(snapshot)})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        assert (await client.get("/readyz")).status_code == 200
