import json
import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from matrusp_mcp.bundles import derive_bundles
from matrusp_mcp.domain import (
    Curriculum,
    CurriculumItem,
    Discipline,
    Meeting,
    OfferingHistory,
    Professor,
    Section,
    Unit,
    Vacancy,
)
from matrusp_mcp.repository import Repository, StaleCursorError
from matrusp_mcp.snapshot import (
    SnapshotData,
    SnapshotMetadata,
    build_snapshot,
    enforce_count_delta,
    load_previous_cache,
    merge_offering_history,
    publish_artifacts,
    snapshot_sha256,
    validate_snapshot,
)


def sample_data(snapshot_id: str = "test-snapshot") -> SnapshotData:
    sections = (
        Section(
            id="section:MAC0001:20262A",
            discipline_code="MAC0001",
            section_code="20262A",
            period_code="20262",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 12, 20),
            section_type="Teórica",
            notes="",
            schedule_status="complete",
            meetings=(
                Meeting("mon", 600, 720, date(2026, 8, 1), date(2026, 12, 20), "10:00", "12:00"),
            ),
            professors=(Professor.from_source("(R) Ada Lovelace"),),
        ),
        Section(
            id="section:MAC0002:20262B",
            discipline_code="MAC0002",
            section_code="20262B",
            period_code="20262",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 12, 20),
            section_type="Teórica",
            notes="",
            schedule_status="unknown",
        ),
    )
    metadata = SnapshotMetadata(
        snapshot_id=snapshot_id,
        schema_version=1,
        crawl_started_at=datetime(2026, 8, 25, tzinfo=UTC),
        crawl_finished_at=datetime(2026, 8, 25, 1, tzinfo=UTC),
        observed_at=datetime(2026, 8, 25, tzinfo=UTC),
        crawler_commit="abc123",
        source_urls=("https://uspdigital.usp.br/jupiterweb/",),
    )
    curriculum = Curriculum(
        "curriculum:CC:bacharelado",
        "CC",
        "bacharelado",
        "Ciência da Computação",
        "45",
        "São Paulo",
        "2026",
        (
            CurriculumItem(
                "curriculum:CC:bacharelado",
                "1",
                "MAC0001",
                "obrigatoria",
                ("MAC0002",),
                ("MAC0002",),
                ("MAC0001",),
            ),
        ),
    )
    return SnapshotData(
        metadata=metadata,
        units=(
            Unit("45", "Instituto de Matemática e Estatística", "São Paulo", None, "override:v1"),
        ),
        disciplines=(
            Discipline("MAC0001", "Programação", "45", "Computação", "1", 4, 0),
            Discipline("MAC0002", "Introdução à Computação", "45", "Computação", "1", 4, 0),
            Discipline(
                "MAC9999", "Tópicos sem oferta", "45", "Computação", "1", 2, 0, is_stub=True
            ),
        ),
        sections=sections,
        bundles=derive_bundles(sections),
        curricula=(curriculum,),
        vacancies=(
            Vacancy(
                "section:MAC0001:20262A",
                "Optativa",
                None,
                "10",
                "4",
                "1",
                "3",
                "2026-08-25T00:00:00Z",
            ),
        ),
        offering_history=(
            OfferingHistory("MAC0001", "20262", "2026-08-01T00:00:00Z", "2026-08-25T00:00:00Z", 1),
        ),
    )


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    path = tmp_path / "snapshot.sqlite"
    build_snapshot(sample_data(), path)
    return path


def test_snapshot_integrity_schema_fts_and_manifest(snapshot: Path) -> None:
    report = validate_snapshot(snapshot)
    assert report.ok
    assert report.counts["disciplines"] == 3
    with sqlite3.connect(snapshot) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT count(*) FROM discipline_fts WHERE discipline_fts MATCH 'programacao'"
        ).fetchone() == (1,)
        manifest = json.loads(
            connection.execute("SELECT manifest_json FROM snapshot_metadata").fetchone()[0]
        )
    assert manifest["snapshot_id"] == "test-snapshot"
    assert manifest["license"] == "AGPL-3.0-only"


def test_read_only_repository_search_order_filters_unknown_and_paginates(snapshot: Path) -> None:
    repository = Repository(snapshot)
    first = repository.search_offerings(query="mac", limit=1)
    assert [item["code"] for item in first.items] == ["MAC0001"]
    assert first.next_cursor is None
    assert repository.search_offerings(query="introducao").items == ()
    assert repository.get_discipline("mac9999")["is_stub"] is True


def test_repository_filters_and_window_modes(snapshot: Path) -> None:
    repository = Repository(snapshot)
    assert repository.search_offerings(
        query="programação", professor="ada", campus="são paulo"
    ).items
    assert repository.search_offerings(unit_code="45", department="computacao", days=("mon",)).items
    assert repository.search_offerings(window=(590, 610), window_mode="overlaps").items
    assert repository.search_offerings(window=(590, 730), window_mode="contained").items
    assert repository.search_offerings(query="mac", include_unknown=True).items
    assert repository.all_bundles("MAC0001", selectable_only=True)
    with pytest.raises(ValueError):
        repository.search_offerings(limit=51)
    with pytest.raises(StaleCursorError):
        repository.search_offerings(cursor="not-a-cursor")
    repository.close()


def test_overlap_day_and_window_must_match_the_same_meeting(tmp_path: Path) -> None:
    data = sample_data()
    original = data.sections[0]
    multi_day = replace(
        original,
        meetings=(
            Meeting(
                "tue", 600, 660, original.start_date, original.end_date, "10:00", "11:00"
            ),
            Meeting(
                "wed", 900, 960, original.start_date, original.end_date, "15:00", "16:00"
            ),
        ),
    )
    path = tmp_path / "multi-day.sqlite"
    build_snapshot(
        replace(
            data,
            sections=(multi_day, data.sections[1]),
            bundles=derive_bundles((multi_day, data.sections[1])),
        ),
        path,
    )
    with Repository(path) as repository:
        assert repository.search_offerings(days=("tue",), window=(620, 630)).items
        assert repository.search_offerings(days=("tue",), window=(900, 930)).items == ()
        assert repository.search_offerings(days=("tue",), window=(660, 700)).items == ()
        assert repository.search_offerings(days=("tue",), window=(590, 600)).items == ()
        assert repository.search_offerings(days=("wed",), window=(900, 930)).items


def test_cursor_from_another_snapshot_is_rejected(snapshot: Path, tmp_path: Path) -> None:
    repository = Repository(snapshot)
    cursor = repository.encode_cursor(score=1.0, last_id="bundle:MAC0001:20262A")
    other_path = tmp_path / "other.sqlite"
    build_snapshot(sample_data("other"), other_path)
    with pytest.raises(StaleCursorError):
        Repository(other_path).search_offerings(cursor=cursor)


def test_repository_exposes_sections_vacancies_origins_and_rejects_malformed_cursors(snapshot: Path) -> None:
    with Repository(snapshot) as repository:
        assert repository._meetings(()) == ()
        assert repository._professors(()) == ()
        bundle = repository.get_bundle("bundle:MAC0001:20262A")
        assert bundle is not None
        assert bundle["sections"] and bundle["vacancies"]
        assert repository.has_section("section:MAC0002:20262B")
        assert not repository.has_section("section:missing")
        assert repository.get_section_professors("section:MAC0001:20262A")
        for value in ("e30", "eyJzbmFwc2hvdF9pZCI6ICJ0ZXN0In0"):
            with pytest.raises(StaleCursorError):
                repository.search_offerings(cursor=value)
        discipline = repository.get_discipline("MAC0001")
        assert discipline is not None and discipline["version_records"]
        page = repository.search_offerings(limit=1, include_unknown=True)
        assert page.next_cursor is not None
        assert repository.search_offerings(limit=1, include_unknown=True, cursor=page.next_cursor).items


def test_repository_context_and_not_found(snapshot: Path) -> None:
    with Repository(snapshot) as repository:
        assert repository.get_discipline("missing") is None
        assert repository.get_bundle("missing") is None
        assert repository.get_curriculum("missing") is None
        assert repository.search_curricula("computacao")
        assert repository.get_curriculum("curriculum:CC:bacharelado") is not None
        assert repository.search_curricula("nothing") == ()


def test_validate_corrupt_and_missing_snapshot(tmp_path: Path) -> None:
    missing = validate_snapshot(tmp_path / "missing.sqlite")
    assert not missing.ok
    broken = tmp_path / "broken.sqlite"
    broken.write_bytes(b"not sqlite")
    assert validate_snapshot(broken).ok is False


def test_previous_cache_and_release_artifacts_are_reproducible(snapshot: Path, tmp_path: Path) -> None:
    cache = load_previous_cache(snapshot)
    assert ("MAC0001", "1") in cache.versions
    artifacts = publish_artifacts(snapshot, tmp_path / "release-1")
    repeated = publish_artifacts(snapshot, tmp_path / "release-2")
    assert all(Path(value).exists() for key, value in artifacts.items() if key != "snapshot_id")
    assert "matrusp-snapshot-test-snapshot.sqlite.gz" in str(artifacts["snapshot"])
    for key in ("snapshot", "manifest", "checksums"):
        assert Path(artifacts[key]).read_bytes() == Path(repeated[key]).read_bytes()
    expected_checksums = (
        f"{snapshot_sha256(Path(artifacts['snapshot']))}  {Path(artifacts['snapshot']).name}\n"
        f"{snapshot_sha256(Path(artifacts['manifest']))}  {Path(artifacts['manifest']).name}\n"
    )
    assert Path(artifacts["checksums"]).read_text(encoding="utf-8") == expected_checksums
    with pytest.raises(ValueError, match="invalid snapshot"):
        publish_artifacts(tmp_path / "missing.sqlite", tmp_path / "bad-release")


def test_validation_detects_silent_loss_of_curriculum_items(snapshot: Path) -> None:
    with sqlite3.connect(snapshot) as connection:
        connection.execute("DELETE FROM prerequisites")
        connection.execute("DELETE FROM curriculum_items")

    report = validate_snapshot(snapshot)

    assert not report.ok
    assert "manifest count mismatch: curriculum_items" in report.errors


def test_empty_curricula_require_an_explicit_collection_state(tmp_path: Path) -> None:
    data = sample_data()
    empty_curriculum = replace(data.curricula[0], items=())
    unclassified = replace(data, curricula=(empty_curriculum,))

    with pytest.raises(ValueError, match="unclassified empty curricula"):
        build_snapshot(unclassified, tmp_path / "unclassified.sqlite")

    classified = replace(
        unclassified,
        metadata=replace(data.metadata, state_counts={"no_current_curriculum": 1}),
    )
    build_snapshot(classified, tmp_path / "classified.sqlite")
    assert validate_snapshot(tmp_path / "classified.sqlite").ok


def test_unfiltered_large_snapshot_requires_a_search_filter(tmp_path: Path) -> None:
    base = sample_data()
    disciplines = tuple(
        Discipline(f"M{i:04d}", f"Disciplina {i}", "45", "Dept", "1", 0, 0)
        for i in range(1001)
    )
    sections = tuple(
        Section(
            f"section:M{i:04d}:20262A",
            f"M{i:04d}",
            "20262A",
            "20262",
            None,
            None,
            "Teórica",
            "",
            "complete",
        )
        for i in range(1001)
    )
    path = tmp_path / "large.sqlite"
    build_snapshot(
        replace(
            base,
            disciplines=disciplines,
            sections=sections,
            bundles=derive_bundles(sections),
            curricula=(),
            vacancies=(),
            offering_history=(),
        ),
        path,
    )
    with Repository(path) as repository:
        with pytest.raises(ValueError, match="requires a query"):
            repository.search_offerings()


def test_atomic_build_preserves_previous_file_on_validation_failure(snapshot: Path) -> None:
    original = snapshot.read_bytes()
    broken = sample_data()
    broken = SnapshotData(
        metadata=broken.metadata,
        units=broken.units,
        disciplines=(),
        sections=broken.sections,
        bundles=broken.bundles,
    )
    with pytest.raises(ValueError, match="foreign key"):
        build_snapshot(broken, snapshot)
    assert snapshot.read_bytes() == original


def test_offering_history_merge_is_idempotent_and_tracks_maximum() -> None:
    first = {("MAC0001", "20262"): ("2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z", 2)}
    second = {("MAC0001", "20262"): ("2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z", 4)}
    merged = merge_offering_history(first, second)
    assert merged == merge_offering_history(merged, second)
    assert merged[("MAC0001", "20262")] == ("2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z", 4)


def test_large_snapshot_delta_requires_explicit_acceptance(snapshot: Path, tmp_path: Path) -> None:
    reduced = tmp_path / "reduced.sqlite"
    data = sample_data()
    build_snapshot(
        SnapshotData(
            metadata=data.metadata,
            units=data.units,
            disciplines=(data.disciplines[0],),
            sections=(data.sections[0],),
            bundles=derive_bundles((data.sections[0],)),
        ),
        reduced,
    )
    with pytest.raises(ValueError, match="large delta"):
        enforce_count_delta(snapshot, reduced)
    enforce_count_delta(snapshot, reduced, accept_large=True)


def test_large_curriculum_delta_requires_explicit_acceptance(
    snapshot: Path, tmp_path: Path
) -> None:
    without_curricula = tmp_path / "without-curricula.sqlite"
    build_snapshot(replace(sample_data(), curricula=()), without_curricula)

    with pytest.raises(ValueError, match="large delta for curricula"):
        enforce_count_delta(snapshot, without_curricula)
    enforce_count_delta(snapshot, without_curricula, accept_large=True)
