from pathlib import Path

import pytest
from mcp import Client

from matrusp_mcp.mcp_server import TOOL_NAMES, create_server
from matrusp_mcp.snapshot import build_snapshot

from .test_snapshot_repository import sample_data


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_real_mcp_client_lists_eight_tools_calls_and_reads_manifest(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.sqlite"
    build_snapshot(sample_data(), snapshot)
    server = create_server(snapshot)
    async with Client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools.tools] == list(TOOL_NAMES)
        result = await client.call_tool("get_discipline", {"request": {"code": "MAC0001"}})
        assert result.is_error is False
        assert result.structured_content is not None
        assert result.structured_content["snapshot_id"] == "test-snapshot"
        resource = await client.read_resource("matrusp://snapshot/manifest")
        assert "AGPL-3.0-only" in resource.contents[0].text
