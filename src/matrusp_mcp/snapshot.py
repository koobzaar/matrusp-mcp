"""Construção, validação e publicação atômica de snapshots SQLite."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from .domain import Bundle, Curriculum, Discipline, OfferingHistory, Section, Unit, Vacancy

SCHEMA_VERSION = 1


def merge_offering_history(
    previous: dict[tuple[str, str], tuple[str, str, int]],
    current: dict[tuple[str, str], tuple[str, str, int]],
) -> dict[tuple[str, str], tuple[str, str, int]]:
    """Mescla histórico por chave sem duplicar uma execução do crawler."""
    merged = dict(previous)
    for key, value in current.items():
        if key not in merged:
            merged[key] = value
            continue
        first, last, maximum = merged[key]
        current_first, current_last, current_maximum = value
        merged[key] = (
            min(first, current_first),
            max(last, current_last),
            max(maximum, current_maximum),
        )
    return dict(sorted(merged.items()))


@dataclass(frozen=True, slots=True)
class SnapshotMetadata:
    snapshot_id: str
    schema_version: int
    crawl_started_at: datetime
    crawl_finished_at: datetime
    observed_at: datetime
    crawler_commit: str
    source_urls: tuple[str, ...]
    checksums: dict[str, str] = field(default_factory=dict)
    state_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SnapshotData:
    metadata: SnapshotMetadata
    units: tuple[Unit, ...] = ()
    disciplines: tuple[Discipline, ...] = ()
    sections: tuple[Section, ...] = ()
    bundles: tuple[Bundle, ...] = ()
    curricula: tuple[Curriculum, ...] = ()
    vacancies: tuple[Vacancy, ...] = ()
    offering_history: tuple[OfferingHistory, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidationReport:
    ok: bool
    counts: dict[str, int]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PreviousSnapshotCache:
    """Rich discipline-version cache and offering history from a prior release."""

    versions: dict[tuple[str, str], dict[str, object]]
    offering_history: dict[tuple[str, str], OfferingHistory]


def load_previous_cache(path: Path) -> PreviousSnapshotCache:
    """Read only the reusable cache from a previous immutable snapshot."""
    versions: dict[tuple[str, str], dict[str, object]] = {}
    history: dict[tuple[str, str], OfferingHistory] = {}
    with sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro&immutable=1", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        version_rows = connection.execute(
            "SELECT v.discipline_code, v.version, d.name, d.department, d.aula_credits, "
            "d.work_credits, d.objectives, d.summary, d.is_stub "
            "FROM discipline_versions v JOIN disciplines d ON d.code = v.discipline_code"
        ).fetchall()
        for row in version_rows:
            versions[(str(row["discipline_code"]), str(row["version"]))] = {
                "name": row["name"],
                "department": row["department"],
                "aula_credits": int(row["aula_credits"]),
                "work_credits": int(row["work_credits"]),
                "objectives": row["objectives"],
                "summary": row["summary"],
                "is_stub": bool(row["is_stub"]),
            }
        for row in connection.execute("SELECT * FROM offering_history").fetchall():
            value = OfferingHistory(
                str(row["discipline_code"]),
                str(row["period_code"]),
                str(row["first_observed_at"]),
                str(row["last_observed_at"]),
                int(row["max_sections"]),
            )
            history[(value.discipline_code, value.period_code)] = value
    return PreviousSnapshotCache(versions, history)


def enforce_count_delta(previous: Path, current: Path, *, accept_large: bool = False) -> None:
    """Reject unexpected publication-sized changes unless explicitly accepted."""
    if accept_large:
        return
    with sqlite3.connect(f"file:{previous}?mode=ro", uri=True) as old_connection, sqlite3.connect(
        f"file:{current}?mode=ro", uri=True
    ) as new_connection:
        for table in ("disciplines", "sections"):
            old_count = int(old_connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            new_count = int(new_connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            if old_count == 0:
                changed = new_count > 0
            else:
                changed = abs(new_count - old_count) / old_count > 0.20
            if changed:
                raise ValueError(
                    f"large delta for {table}: previous={old_count}, current={new_count}; "
                    "rerun with --accept-large-delta"
                )


DDL = """
PRAGMA foreign_keys = ON;
CREATE TABLE snapshot_metadata (
  snapshot_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL,
  crawl_started_at TEXT NOT NULL,
  crawl_finished_at TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  crawler_commit TEXT NOT NULL,
  source_urls_json TEXT NOT NULL,
  checksums_json TEXT NOT NULL,
  state_counts_json TEXT NOT NULL,
  manifest_json TEXT NOT NULL
);
CREATE TABLE units (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  campus TEXT,
  source_campus_name TEXT,
  provenance TEXT
);
CREATE TABLE disciplines (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  unit_code TEXT REFERENCES units(code),
  department TEXT,
  aula_credits INTEGER NOT NULL,
  work_credits INTEGER NOT NULL,
  objectives TEXT,
  summary TEXT,
  is_stub INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE discipline_units (
  discipline_code TEXT NOT NULL REFERENCES disciplines(code),
  unit_code TEXT NOT NULL REFERENCES units(code),
  PRIMARY KEY (discipline_code, unit_code)
);
CREATE TABLE discipline_versions (
  discipline_code TEXT NOT NULL REFERENCES disciplines(code),
  version TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  PRIMARY KEY (discipline_code, version)
);
CREATE TABLE sections (
  id TEXT PRIMARY KEY,
  discipline_code TEXT NOT NULL REFERENCES disciplines(code),
  section_code TEXT NOT NULL,
  period_code TEXT NOT NULL,
  start_date TEXT,
  end_date TEXT,
  section_type TEXT NOT NULL,
  notes TEXT NOT NULL,
  schedule_status TEXT NOT NULL,
  data_quality_flags_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE meetings (
  id INTEGER PRIMARY KEY,
  section_id TEXT NOT NULL REFERENCES sections(id),
  day TEXT NOT NULL,
  start_minute INTEGER,
  end_minute INTEGER,
  start_date TEXT,
  end_date TEXT,
  start_text TEXT NOT NULL,
  end_text TEXT NOT NULL,
  original_day TEXT NOT NULL
);
CREATE TABLE professors (
  section_id TEXT NOT NULL REFERENCES sections(id),
  display_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  responsible INTEGER NOT NULL,
  PRIMARY KEY (section_id, display_name)
);
CREATE TABLE vacancies (
  id INTEGER PRIMARY KEY,
  section_id TEXT NOT NULL REFERENCES sections(id),
  category TEXT NOT NULL,
  group_name TEXT,
  available_text TEXT,
  registered_text TEXT,
  pending_text TEXT,
  enrolled_text TEXT,
  observed_at TEXT NOT NULL
);
CREATE TABLE section_links (
  practice_section_id TEXT NOT NULL REFERENCES sections(id),
  theory_section_id TEXT NOT NULL,
  PRIMARY KEY (practice_section_id, theory_section_id)
);
CREATE TABLE bundles (
  id TEXT PRIMARY KEY,
  discipline_code TEXT NOT NULL REFERENCES disciplines(code),
  selectable INTEGER NOT NULL,
  schedule_status TEXT NOT NULL,
  data_quality_flags_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE bundle_sections (
  bundle_id TEXT NOT NULL REFERENCES bundles(id),
  section_id TEXT NOT NULL REFERENCES sections(id),
  ordinal INTEGER NOT NULL,
  PRIMARY KEY (bundle_id, section_id)
);
CREATE TABLE curricula (
  id TEXT PRIMARY KEY,
  course_code TEXT NOT NULL,
  habilitation_code TEXT NOT NULL,
  name TEXT NOT NULL,
  unit_code TEXT REFERENCES units(code),
  campus TEXT,
  period_code TEXT
);
CREATE TABLE curriculum_items (
  id INTEGER PRIMARY KEY,
  curriculum_id TEXT NOT NULL REFERENCES curricula(id),
  ideal_period TEXT NOT NULL,
  discipline_code TEXT NOT NULL REFERENCES disciplines(code),
  item_type TEXT NOT NULL,
  name TEXT,
  aula_credits INTEGER,
  work_credits INTEGER
);
CREATE TABLE prerequisites (
  curriculum_item_id INTEGER NOT NULL REFERENCES curriculum_items(id),
  relation TEXT NOT NULL,
  prerequisite_code TEXT NOT NULL,
  PRIMARY KEY (curriculum_item_id, relation, prerequisite_code)
);
CREATE TABLE offering_history (
  discipline_code TEXT NOT NULL REFERENCES disciplines(code),
  period_code TEXT NOT NULL,
  first_observed_at TEXT NOT NULL,
  last_observed_at TEXT NOT NULL,
  max_sections INTEGER NOT NULL,
  PRIMARY KEY (discipline_code, period_code)
);
CREATE VIRTUAL TABLE discipline_fts USING fts5(code, name, department, content='');
CREATE VIRTUAL TABLE professor_fts USING fts5(section_id, display_name, normalized_name, content='');
CREATE INDEX sections_period_idx ON sections(period_code);
CREATE INDEX sections_discipline_idx ON sections(discipline_code);
CREATE INDEX meetings_day_time_idx ON meetings(day, start_minute, end_minute);
CREATE INDEX professors_name_idx ON professors(normalized_name);
"""


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _manifest(data: SnapshotData, counts: dict[str, int]) -> dict[str, object]:
    metadata = data.metadata
    return {
        "snapshot_id": metadata.snapshot_id,
        "schema_version": metadata.schema_version,
        "license": "AGPL-3.0-only",
        "source_code_url": "https://github.com/matrusp/matrusp-mcp",
        "observed_at": _iso(metadata.observed_at),
        "crawler_commit": metadata.crawler_commit,
        "source_urls": list(metadata.source_urls),
        "checksums": metadata.checksums,
        "state_counts": metadata.state_counts,
        "counts": counts,
        "mcp": {"server": "matrusp-mcp", "transport": ["stdio", "streamable-http"]},
    }


def _insert(connection: sqlite3.Connection, data: SnapshotData) -> None:
    metadata = data.metadata
    connection.executescript(DDL)
    observed = _iso(metadata.observed_at)
    connection.executemany(
        "INSERT INTO units VALUES (?, ?, ?, ?, ?)",
        [
            (unit.code, unit.name, unit.campus, unit.source_campus_name, unit.provenance)
            for unit in data.units
        ],
    )
    connection.executemany(
        "INSERT INTO disciplines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                discipline.code,
                discipline.name,
                discipline.unit_code,
                discipline.department,
                discipline.aula_credits,
                discipline.work_credits,
                discipline.objectives,
                discipline.summary,
                int(discipline.is_stub),
            )
            for discipline in data.disciplines
        ],
    )
    connection.executemany(
        "INSERT INTO discipline_versions VALUES (?, ?, ?)",
        [
            (discipline.code, version, observed)
            for discipline in data.disciplines
            for version in (discipline.versions or ((discipline.version,) if discipline.version else ()))
        ],
    )
    connection.executemany(
        "INSERT INTO discipline_units VALUES (?, ?)",
        [
            (discipline.code, unit_code)
            for discipline in data.disciplines
            for unit_code in (discipline.unit_codes or ((discipline.unit_code,) if discipline.unit_code else ()))
        ],
    )
    connection.executemany(
        "INSERT INTO sections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                section.id,
                section.discipline_code,
                section.section_code,
                section.period_code,
                _date(section.start_date),
                _date(section.end_date),
                section.section_type,
                section.notes,
                section.schedule_status,
                json.dumps(section.data_quality_flags),
            )
            for section in data.sections
        ],
    )
    meeting_rows: list[tuple[object, ...]] = []
    professor_rows: set[tuple[str, str, str, int]] = set()
    for section in data.sections:
        for meeting in section.meetings:
            meeting_rows.append(
                (
                    section.id,
                    meeting.day,
                    meeting.start_minute,
                    meeting.end_minute,
                    _date(meeting.start_date),
                    _date(meeting.end_date),
                    meeting.start_text,
                    meeting.end_text,
                    meeting.original_day,
                )
            )
        for professor in section.professors:
            professor_rows.add(
                (
                    section.id,
                    professor.display_name,
                    professor.normalized_name,
                    int(professor.responsible),
                )
            )
    connection.executemany(
        "INSERT INTO meetings(section_id, day, start_minute, end_minute, start_date, end_date, start_text, end_text, original_day) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        meeting_rows,
    )
    connection.executemany("INSERT INTO professors VALUES (?, ?, ?, ?)", sorted(professor_rows))
    connection.executemany(
        "INSERT INTO vacancies(section_id, category, group_name, available_text, registered_text, pending_text, enrolled_text, observed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                vacancy.section_id,
                vacancy.category,
                vacancy.group_name,
                vacancy.available_text,
                vacancy.registered_text,
                vacancy.pending_text,
                vacancy.enrolled_text,
                vacancy.observed_at,
            )
            for vacancy in data.vacancies
        ],
    )
    connection.executemany(
        "INSERT INTO section_links VALUES (?, ?)",
        [
            (section.id, f"section:{section.discipline_code}:{section.linked_theory_section_code}")
            for section in data.sections
            if section.linked_theory_section_code
        ],
    )
    connection.executemany(
        "INSERT INTO bundles VALUES (?, ?, ?, ?, ?)",
        [
            (
                bundle.id,
                bundle.discipline_code,
                int(bundle.selectable),
                bundle.schedule_status,
                json.dumps(bundle.data_quality_flags),
            )
            for bundle in data.bundles
        ],
    )
    connection.executemany(
        "INSERT INTO bundle_sections VALUES (?, ?, ?)",
        [
            (bundle.id, section_id, ordinal)
            for bundle in data.bundles
            for ordinal, section_id in enumerate(bundle.section_ids)
        ],
    )
    curriculum_item_rows: list[tuple[int, str, str, str, str, str | None, int | None, int | None]] = []
    prerequisite_rows: list[tuple[int, str, str]] = []
    item_id = 1
    for curriculum in data.curricula:
        connection.execute(
            "INSERT INTO curricula VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                curriculum.id,
                curriculum.course_code,
                curriculum.habilitation_code,
                curriculum.name,
                curriculum.unit_code,
                curriculum.campus,
                curriculum.period_code,
            ),
        )
        for item in curriculum.items:
            curriculum_item_rows.append(
                (
                    item_id,
                    curriculum.id,
                    item.ideal_period,
                    item.discipline_code,
                    item.item_type,
                    item.name,
                    item.aula_credits,
                    item.work_credits,
                )
            )
            for relation, values in (
                ("weak", item.weak_prerequisites),
                ("strong", item.strong_prerequisites),
                ("set", item.set_indications),
            ):
                prerequisite_rows.extend((item_id, relation, value) for value in values)
            item_id += 1
    connection.executemany(
        "INSERT INTO curriculum_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)", curriculum_item_rows
    )
    connection.executemany("INSERT INTO prerequisites VALUES (?, ?, ?)", prerequisite_rows)
    connection.executemany(
        "INSERT INTO offering_history VALUES (?, ?, ?, ?, ?)",
        [
            (
                item.discipline_code,
                item.period_code,
                item.first_observed_at,
                item.last_observed_at,
                item.max_sections,
            )
            for item in data.offering_history
        ],
    )
    connection.executemany(
        "INSERT INTO discipline_fts(rowid, code, name, department) VALUES (?, ?, ?, ?)",
        [
            (index, d.code, d.name, d.department or "")
            for index, d in enumerate(data.disciplines, 1)
        ],
    )
    connection.executemany(
        "INSERT INTO professor_fts(rowid, section_id, display_name, normalized_name) VALUES (?, ?, ?, ?)",
        [(index, row[0], row[1], row[2]) for index, row in enumerate(sorted(professor_rows), 1)],
    )
    counts = {
        table: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        for table in ("units", "disciplines", "sections", "meetings", "bundles", "curricula")
    }
    manifest = _manifest(data, counts)
    connection.execute(
        "INSERT INTO snapshot_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            metadata.snapshot_id,
            metadata.schema_version,
            _iso(metadata.crawl_started_at),
            _iso(metadata.crawl_finished_at),
            observed,
            metadata.crawler_commit,
            json.dumps(metadata.source_urls),
            json.dumps(metadata.checksums),
            json.dumps(metadata.state_counts),
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        ),
    )
    connection.execute("PRAGMA user_version = 1")
    connection.commit()


def build_snapshot(data: SnapshotData, destination: Path) -> None:
    """Constrói em arquivo irmão temporário e só promove após integridade completa."""
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with sqlite3.connect(temporary) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            try:
                _insert(connection, data)
            except sqlite3.IntegrityError as error:
                raise ValueError("foreign key validation failed") from error
            report = validate_snapshot(temporary)
            if not report.ok:
                raise ValueError("; ".join(report.errors))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def publish_artifacts(snapshot: Path, destination: Path) -> dict[str, Path | str]:
    """Create the immutable gzip snapshot, manifest and checksum file.

    The function is deliberately local and side-effect-limited; a CI workflow may
    upload these files to a GitHub Release only after this operation succeeds.
    """
    report = validate_snapshot(snapshot)
    if not report.ok:
        raise ValueError("cannot publish invalid snapshot: " + "; ".join(report.errors))
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{Path(snapshot).resolve()}?mode=ro&immutable=1", uri=True) as connection:
        row = connection.execute(
            "SELECT snapshot_id, manifest_json FROM snapshot_metadata"
        ).fetchone()
    if row is None:
        raise ValueError("snapshot metadata is missing")
    snapshot_id, manifest_json = str(row[0]), str(row[1])
    compressed = destination / f"matrusp-snapshot-{snapshot_id}.sqlite.gz"
    manifest = destination / f"manifest-{snapshot_id}.json"
    checksums = destination / "SHA256SUMS"
    # Write through temporary siblings so a failed compression never leaves a partial artifact.
    compressed_tmp = compressed.with_suffix(compressed.suffix + ".tmp")
    manifest_tmp = manifest.with_suffix(manifest.suffix + ".tmp")
    checksums_tmp = checksums.with_suffix(checksums.suffix + ".tmp")
    try:
        with Path(snapshot).open("rb") as source, compressed_tmp.open("wb") as raw_target:
            target = gzip.GzipFile(fileobj=raw_target, mode="wb", mtime=0)
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                target.write(chunk)
            target.close()
        manifest_tmp.write_text(
            json.dumps(json.loads(manifest_json), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        checksums_tmp.write_text(
            f"{snapshot_sha256(compressed_tmp)}  {compressed.name}\n"
            f"{snapshot_sha256(manifest_tmp)}  {manifest.name}\n",
            encoding="utf-8",
        )
        os.replace(compressed_tmp, compressed)
        os.replace(manifest_tmp, manifest)
        os.replace(checksums_tmp, checksums)
    finally:
        compressed_tmp.unlink(missing_ok=True)
        manifest_tmp.unlink(missing_ok=True)
        checksums_tmp.unlink(missing_ok=True)
    return {"snapshot": compressed, "manifest": manifest, "checksums": checksums, "snapshot_id": snapshot_id}


def validate_snapshot(path: Path) -> ValidationReport:
    errors: list[str] = []
    counts: dict[str, int] = {}
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                errors.append("sqlite integrity check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                errors.append("foreign key check failed")
            required_tables = (
                "snapshot_metadata",
                "units",
                "disciplines",
                "discipline_versions",
                "discipline_units",
                "sections",
                "meetings",
                "professors",
                "vacancies",
                "section_links",
                "bundles",
                "bundle_sections",
                "curricula",
                "curriculum_items",
                "prerequisites",
                "offering_history",
            )
            actual_tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow')"
                ).fetchall()
            }
            for table in required_tables:
                if table not in actual_tables:
                    errors.append(f"required table missing: {table}")
            for table in ("units", "disciplines", "sections", "meetings", "bundles", "curricula"):
                if table not in actual_tables:
                    continue
                counts[table] = int(
                    connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                )
            row = connection.execute("SELECT manifest_json FROM snapshot_metadata").fetchone()
            if row is None:
                errors.append("manifest missing")
            else:
                manifest = json.loads(row[0])
                if manifest.get("schema_version") != SCHEMA_VERSION:
                    errors.append("schema version mismatch")
                manifest_counts = manifest.get("counts", {})
                if isinstance(manifest_counts, dict):
                    for table, count in counts.items():
                        if manifest_counts.get(table) != count:
                            errors.append(f"manifest count mismatch: {table}")
            invalid_states = connection.execute(
                "SELECT DISTINCT schedule_status FROM sections "
                "WHERE schedule_status NOT IN ('complete', 'partial', 'unknown')"
            ).fetchall()
            if invalid_states:
                errors.append("invalid schedule status")
            invalid_selectable = connection.execute(
                "SELECT count(*) FROM bundles WHERE selectable = 1 AND schedule_status != 'complete'"
            ).fetchone()[0]
            if invalid_selectable:
                errors.append("incomplete bundle marked selectable")
            for table, columns in {
                "discipline_fts": ("code", "name", "department"),
                "professor_fts": ("section_id", "display_name", "normalized_name"),
            }.items():
                if table not in actual_tables:
                    errors.append(f"required virtual table missing: {table}")
                else:
                    actual_columns = {
                        str(item[1])
                        for item in connection.execute(f"PRAGMA table_info({table})").fetchall()
                    }
                    if not set(columns).issubset(actual_columns):
                        errors.append(f"invalid FTS schema: {table}")
    except (OSError, sqlite3.DatabaseError, json.JSONDecodeError) as error:
        errors.append(f"invalid snapshot: {error}")
    return ValidationReport(not errors, counts, tuple(errors))


def snapshot_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
