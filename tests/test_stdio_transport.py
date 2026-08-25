import sys
from pathlib import Path

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters


@pytest.mark.asyncio
async def test_stdio_transport_round_trip(tmp_path: Path) -> None:
    from matrusp_mcp.bootstrap import bootstrap_data
    from matrusp_mcp.snapshot import build_snapshot

    snapshot = tmp_path / "snapshot.sqlite"
    build_snapshot(bootstrap_data(), snapshot)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "matrusp_mcp.cli", "serve", "--transport", "stdio", "--snapshot", str(snapshot)],
        cwd=Path.cwd(),
    )
    async with Client(parameters, read_timeout_seconds=10) as client:
        tools = await client.list_tools()
        result = await client.call_tool("get_discipline", {"request": {"code": "MAC0101"}})
    assert len(tools.tools) == 8
    assert result.is_error is False
