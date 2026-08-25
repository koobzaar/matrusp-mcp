import json
from pathlib import Path

from matrusp_mcp.cli import main
from matrusp_mcp.snapshot import build_snapshot

from .test_snapshot_repository import sample_data


def test_validate_command_reports_json_and_exit_status(tmp_path: Path, capsys: object) -> None:
    snapshot = tmp_path / "snapshot.sqlite"
    build_snapshot(sample_data(), snapshot)
    assert main(["validate", str(snapshot)]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["ok"] is True
