"""Black-box contracts for the remote MCP endpoint used by plugin hosts."""

from __future__ import annotations

import asyncio
import json
import shutil
import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import httpx2
import pytest
from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from matrusp_mcp.http_server import create_http_app
from matrusp_mcp.mcp_server import TOOL_NAMES
from matrusp_mcp.vercel import create_vercel_app


@asynccontextmanager
async def running_app(app: Any) -> AsyncIterator[None]:
    started = asyncio.Event()
    stopped = asyncio.Event()
    messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def receive() -> dict[str, Any]:
        return await messages.get()

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "lifespan.startup.complete":
            started.set()
        if message["type"] == "lifespan.shutdown.complete":
            stopped.set()

    task = asyncio.create_task(
        app({"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send)
    )
    await messages.put({"type": "lifespan.startup"})
    await started.wait()
    try:
        yield
    finally:
        await messages.put({"type": "lifespan.shutdown"})
        await stopped.wait()
        await task


@asynccontextmanager
async def remote_client(app: Any, base_url: str = "http://testserver") -> AsyncIterator[Client]:
    async with running_app(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url=base_url
        ) as http_client:
            transport = streamable_http_client(
                f"{base_url}/mcp", http_client=http_client, terminate_on_close=False
            )
            async with Client(transport, mode="legacy", read_timeout_seconds=10) as client:
                yield client


def tool_error_payload(text: str) -> dict[str, str]:
    return json.loads(text[text.index("{") :])


def make_app(tmp_path: Path, **kwargs: Any) -> Any:
    snapshot = tmp_path / "snapshot.sqlite"
    shutil.copyfile(Path(__file__).parents[1] / "data" / "matrusp.sqlite", snapshot)
    return create_http_app(snapshot, **kwargs)


@pytest.mark.asyncio
async def test_remote_mcp_client_completes_lifecycle_and_reads_server_metadata(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    async with remote_client(app) as client:
        assert client.protocol_version
        assert client.server_info is not None
        assert client.server_info.name == "matrusp-mcp"
        assert client.server_info.version == "0.1.0"
        assert client.instructions is not None
        assert "read-only" in client.instructions.casefold()

        tools = await client.list_tools()
        assert [tool.name for tool in tools.tools] == list(TOOL_NAMES)
        result = await client.call_tool("get_discipline", {"request": {"code": "MAC0101"}})

        assert result.is_error is False
        assert result.structured_content is not None
        assert result.structured_content["snapshot_id"] == "bootstrap-20260825"
        assert result.content
        assert json.loads(result.content[0].text) == result.structured_content

        resources = await client.list_resources()
        assert [resource.uri for resource in resources.resources] == [
            "matrusp://snapshot/manifest"
        ]
        manifest = await client.read_resource("matrusp://snapshot/manifest")
        assert "AGPL-3.0-only" in manifest.contents[0].text


@pytest.mark.asyncio
async def test_remote_tool_discovery_exposes_valid_schemas_titles_and_read_only_annotations(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    async with remote_client(app) as client:
        tools = await client.list_tools()

    for tool in tools.tools:
        assert tool.title
        assert tool.description
        assert tool.input_schema["type"] == "object"
        assert "request" in tool.input_schema["required"]
        Draft202012Validator.check_schema(tool.input_schema)
        assert tool.output_schema is not None
        assert tool.output_schema["type"] == "object"
        Draft202012Validator.check_schema(tool.output_schema)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.annotations.open_world_hint is False


@pytest.mark.asyncio
async def test_remote_tool_errors_are_model_readable_and_validation_is_enforced(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    async with remote_client(app) as client:
        not_found = await client.call_tool(
            "get_discipline", {"request": {"code": "DOES_NOT_EXIST"}}
        )
        invalid = await client.call_tool("search_offerings", {"request": {"limit": 0}})

    assert not_found.is_error is True
    assert tool_error_payload(not_found.content[0].text) == {
        "code": "not_found",
        "message": "discipline not found: DOES_NOT_EXIST",
    }
    assert invalid.is_error is True
    assert "greater than or equal to 1" in invalid.content[0].text


@pytest.mark.asyncio
async def test_remote_endpoint_is_stateless_and_does_not_rate_limit_read_only_calls(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    async with remote_client(app) as first_client:
        first = await first_client.call_tool(
            "get_discipline", {"request": {"code": "MAC0101"}}
        )
    async with remote_client(app) as second_client:
        second = await second_client.call_tool(
            "get_discipline", {"request": {"code": "MAC0101"}}
        )
        results = [
            await asyncio.wait_for(
                second_client.call_tool("get_discipline", {"request": {"code": "MAC0101"}}),
                timeout=2,
            )
            for _ in range(25)
        ]

    assert first.is_error is False
    assert second.is_error is False
    assert all(result.is_error is False for result in results)


@pytest.mark.asyncio
async def test_streamable_http_uses_json_responses_and_allows_405_get_for_stateless_mode(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "contract-test", "version": "1.0"},
        },
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    async with running_app(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post("/mcp", headers=headers, json=initialize)
            get_response = await client.get("/mcp", headers={"Accept": "text/event-stream"})
            unknown_route = await client.post("/not-mcp", headers=headers, json=initialize)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "mcp-session-id" not in response.headers
    assert response.json()["result"]["serverInfo"]["name"] == "matrusp-mcp"
    assert get_response.status_code == 405
    assert unknown_route.status_code == 404


@pytest.mark.asyncio
async def test_http_accepts_configured_origin_and_rejects_wrong_content_type(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path, allowed_origins=("https://chatgpt.com",))

    async with running_app(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            allowed_origin = await client.get(
                "/healthz", headers={"Origin": "https://chatgpt.com"}
            )
            wrong_content_type = await client.post(
                "/mcp",
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "text/plain",
                },
                content="not-json",
            )

    assert allowed_origin.status_code == 200
    assert wrong_content_type.status_code == 400


@pytest.mark.asyncio
async def test_http_security_rejects_untrusted_origin_and_oversized_mcp_body(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    oversized = b"x" * (256 * 1024 + 1)

    async with running_app(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            origin_response = await client.get(
                "/healthz", headers={"Origin": "https://evil.example"}
            )
            oversized_response = await client.post(
                "/mcp",
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                content=oversized,
            )

    assert origin_response.status_code == 403
    assert oversized_response.status_code == 413


def test_coverage_measures_the_mcp_and_http_surfaces() -> None:
    config = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    omitted = set(config["tool"]["coverage"]["run"]["omit"])

    assert not any(path.endswith("http_server.py") for path in omitted)
    assert not any(path.endswith("mcp_server.py") for path in omitted)


@pytest.mark.asyncio
async def test_vercel_app_accepts_a_platform_host_with_the_real_mcp_client(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "snapshot.sqlite"
    shutil.copyfile(Path(__file__).parents[1] / "data" / "matrusp.sqlite", snapshot)
    app = create_vercel_app(
        tmp_path,
        environment={
            "MATRUSP_SNAPSHOT": snapshot.name,
            "VERCEL_URL": "matrusp-preview.vercel.app",
        },
    )

    async with remote_client(app, "https://matrusp-preview.vercel.app") as client:
        result = await client.call_tool("get_discipline", {"request": {"code": "MAC0101"}})

    assert result.is_error is False
