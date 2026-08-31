from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "snapshot.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_snapshot_workflow_promotes_only_after_validation_and_pushes_for_vercel() -> None:
    workflow = _workflow_text()

    validation = workflow.index(
        "uv run --locked matrusp-mcp validate /tmp/matrusp.sqlite"
    )
    promotion = workflow.index("cp /tmp/matrusp.sqlite data/matrusp.sqlite")
    docker_gate = workflow.index("- name: Gate release on a verified image build")
    commit = workflow.index("- name: Commit snapshot for Vercel deployment")
    release = workflow.index("- name: Create immutable GitHub Release")

    assert validation < promotion < docker_gate < commit < release
    assert "git add data/matrusp.sqlite" in workflow
    assert "git push origin HEAD:main" in workflow
    commit_start = workflow.index("- name: Commit snapshot for Vercel deployment")
    release_start = workflow.index("- name: Create immutable GitHub Release")
    commit_step = workflow[commit_start:release_start]

    assert "git diff --cached --quiet" in commit_step
    assert "git add ." not in commit_step
    assert "git add -A" not in commit_step
    assert 'SNAPSHOT_COMMIT_SHA=$(git rev-parse HEAD)' in commit_step
