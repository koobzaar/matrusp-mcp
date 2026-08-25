"""Camada de leitura imutável sobre o snapshot."""

from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

from .domain import ConflictState, Meeting
from .normalize import normalize_day, normalize_text
from .temporal import conflict_between


class StaleCursorError(ValueError):
    """Cursor emitido para outro snapshot."""


class SearchTooBroadError(ValueError):
    """A deliberately unfiltered search would exceed the bounded response universe."""


@dataclass(frozen=True, slots=True)
class SearchPage:
    items: tuple[dict[str, object], ...]
    next_cursor: str | None


class Repository:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self._connection = sqlite3.connect(
            f"file:{self.path}?mode=ro&immutable=1", uri=True, check_same_thread=False
        )
        self._connection.execute("PRAGMA query_only=ON")
        self._connection.row_factory = sqlite3.Row
        self._has_discipline_units = (
            self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='discipline_units'"
            ).fetchone()
            is not None
        )
        row = self._connection.execute("SELECT * FROM snapshot_metadata").fetchone()
        if row is None:
            self._connection.close()
            raise ValueError("snapshot metadata is missing")
        self.snapshot_id = str(row["snapshot_id"])
        self.observed_at = str(row["observed_at"])
        self.manifest = json.loads(str(row["manifest_json"]))

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Repository:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def encode_cursor(self, score: float, last_id: str) -> str:
        value = json.dumps(
            {"snapshot_id": self.snapshot_id, "score": score, "last_id": last_id},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    def _decode_cursor(self, cursor: str) -> dict[str, object]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            value = json.loads(base64.urlsafe_b64decode(padded).decode())
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise StaleCursorError("invalid cursor") from error
        if not isinstance(value, dict) or value.get("snapshot_id") != self.snapshot_id:
            raise StaleCursorError("cursor belongs to another snapshot")
        if not isinstance(value.get("last_id"), str):
            raise StaleCursorError("invalid cursor")
        try:
            float(cast(float | int | str, value.get("score")))
        except (TypeError, ValueError) as error:
            raise StaleCursorError("invalid cursor") from error
        return value

    @staticmethod
    def _meeting(row: sqlite3.Row) -> Meeting:
        return Meeting(
            str(row["day"]),
            row["start_minute"],
            row["end_minute"],
            date.fromisoformat(row["start_date"]) if row["start_date"] else None,
            date.fromisoformat(row["end_date"]) if row["end_date"] else None,
            str(row["start_text"]),
            str(row["end_text"]),
            str(row["original_day"]),
        )

    def _meetings(self, section_ids: tuple[str, ...] | list[str]) -> tuple[Meeting, ...]:
        if not section_ids:
            return ()
        placeholders = ",".join("?" for _ in section_ids)
        rows = self._connection.execute(
            f"SELECT * FROM meetings WHERE section_id IN ({placeholders}) ORDER BY id", section_ids
        ).fetchall()
        return tuple(self._meeting(row) for row in rows)

    def _professors(
        self, section_ids: tuple[str, ...] | list[str]
    ) -> tuple[dict[str, object], ...]:
        if not section_ids:
            return ()
        placeholders = ",".join("?" for _ in section_ids)
        rows = self._connection.execute(
            f"SELECT display_name, normalized_name, responsible FROM professors WHERE section_id IN ({placeholders}) ORDER BY normalized_name, display_name",
            section_ids,
        ).fetchall()
        return tuple(
            {
                "display_name": row["display_name"],
                "responsible": bool(row["responsible"]),
                "normalized_name": row["normalized_name"],
            }
            for row in rows
        )

    def _unit_codes(self, discipline: sqlite3.Row) -> tuple[str, ...]:
        if not self._has_discipline_units:
            return (str(discipline["unit_code"]),) if discipline["unit_code"] else ()
        rows = self._connection.execute(
            "SELECT unit_code FROM discipline_units WHERE discipline_code = ? ORDER BY unit_code",
            (discipline["code"],),
        ).fetchall()
        return tuple(str(row[0]) for row in rows) or (
            (str(discipline["unit_code"]),) if discipline["unit_code"] else ()
        )

    def _bundle(self, row: sqlite3.Row) -> dict[str, object]:
        sections = self._connection.execute(
            "SELECT section_id FROM bundle_sections WHERE bundle_id = ? ORDER BY ordinal",
            (row["id"],),
        ).fetchall()
        section_ids = tuple(str(item[0]) for item in sections)
        meetings = self._meetings(section_ids)
        section_rows = self._connection.execute(
            "SELECT id, section_code, period_code, start_date, end_date, section_type, notes, "
            "schedule_status, data_quality_flags_json FROM sections "
            f"WHERE id IN ({','.join('?' for _ in section_ids)}) ORDER BY id",
            section_ids,
        ).fetchall() if section_ids else []
        vacancies = self._connection.execute(
            "SELECT section_id, category, group_name, available_text, registered_text, "
            "pending_text, enrolled_text, observed_at FROM vacancies "
            f"WHERE section_id IN ({','.join('?' for _ in section_ids)}) ORDER BY id",
            section_ids,
        ).fetchall() if section_ids else []
        return {
            "id": str(row["id"]),
            "discipline_code": str(row["discipline_code"]),
            "selectable": bool(row["selectable"]),
            "schedule_status": str(row["schedule_status"]),
            "data_quality_flags": json.loads(str(row["data_quality_flags_json"])),
            "section_ids": section_ids,
            "sections": tuple(
                {
                    "id": str(item["id"]),
                    "section_code": str(item["section_code"]),
                    "period_code": str(item["period_code"]),
                    "start_date": item["start_date"],
                    "end_date": item["end_date"],
                    "section_type": item["section_type"],
                    "notes": item["notes"],
                    "schedule_status": item["schedule_status"],
                    "data_quality_flags": json.loads(str(item["data_quality_flags_json"])),
                }
                for item in section_rows
            ),
            "meetings": meetings,
            "professors": self._professors(section_ids),
            "vacancies": tuple(dict(item) for item in vacancies),
        }

    def get_bundle(self, bundle_id: str) -> dict[str, object] | None:
        row = self._connection.execute(
            "SELECT * FROM bundles WHERE id = ?", (bundle_id,)
        ).fetchone()
        return self._bundle(row) if row is not None else None

    def get_section_meetings(self, section_id: str) -> tuple[Meeting, ...]:
        return self._meetings((section_id,))

    def has_section(self, section_id: str) -> bool:
        return (
            self._connection.execute("SELECT 1 FROM sections WHERE id = ?", (section_id,)).fetchone()
            is not None
        )

    def get_section_professors(self, section_id: str) -> tuple[dict[str, object], ...]:
        return self._professors((section_id,))

    def all_bundles(
        self, discipline_code: str | None = None, *, selectable_only: bool = False
    ) -> tuple[dict[str, object], ...]:
        query = "SELECT * FROM bundles"
        clauses: list[str] = []
        parameters: list[object] = []
        if discipline_code:
            clauses.append("discipline_code = ?")
            parameters.append(discipline_code)
        if selectable_only:
            clauses.append("selectable = 1")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        rows = self._connection.execute(query + " ORDER BY id", parameters).fetchall()
        return tuple(self._bundle(row) for row in rows)

    def search_offerings(
        self,
        query: str | None = None,
        *,
        professor: str | None = None,
        campus: str | None = None,
        unit_code: str | None = None,
        department: str | None = None,
        days: tuple[str, ...] = (),
        window: tuple[int, int] | None = None,
        window_mode: str = "overlaps",
        include_unknown: bool = False,
        limit: int = 20,
        cursor: str | None = None,
    ) -> SearchPage:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        cursor_value = self._decode_cursor(cursor) if cursor else None
        normalized_query = normalize_text(query or "")
        normalized_professor = normalize_text(professor or "")
        normalized_campus = normalize_text(campus or "")
        normalized_department = normalize_text(department or "")
        day_set = {normalized for value in days if (normalized := normalize_day(value)) is not None}
        if not any(
            (normalized_query, normalized_professor, normalized_campus, unit_code, normalized_department, day_set, window)
        ):
            selectable_count = int(
                self._connection.execute("SELECT count(*) FROM bundles WHERE selectable = 1").fetchone()[0]
            )
            if selectable_count > 1000:
                raise SearchTooBroadError("search requires a query or filter")
        fts_scores: dict[str, float] = {}
        if normalized_query:
            terms = [term for term in normalized_query.split() if term]
            fts_query = " AND ".join(f'"{term.replace(chr(34), "")}"*' for term in terms)
            try:
                fts_rows = self._connection.execute(
                    "SELECT code, bm25(discipline_fts) AS rank FROM discipline_fts "
                    "WHERE discipline_fts MATCH ? ORDER BY rank, code",
                    (fts_query,),
                ).fetchall()
            except sqlite3.OperationalError:
                fts_rows = []
            fts_scores = {str(item["code"]): float(item["rank"]) for item in fts_rows}
        candidates: list[tuple[float, str, dict[str, object]]] = []
        for bundle in self.all_bundles(selectable_only=not include_unknown):
            discipline = self._connection.execute(
                "SELECT * FROM disciplines WHERE code = ?", (bundle["discipline_code"],)
            ).fetchone()
            if discipline is None:
                continue
            name = str(discipline["name"])
            code = str(discipline["code"])
            haystack = normalize_text(f"{code} {name}")
            if normalized_query:
                if normalized_query == normalize_text(code):
                    score = 0.0
                elif normalize_text(code).startswith(normalized_query):
                    score = 1.0
                elif normalized_query == normalize_text(name):
                    score = 2.0
                elif code in fts_scores:
                    # BM25 is negative in SQLite; convert it to a deterministic tie-breaker.
                    score = 3.0 + max(0.0, min(1.0, abs(fts_scores[code]) / 100.0))
                elif normalized_query in haystack:
                    score = 4.0
                else:
                    continue
            else:
                score = 3.0
            unit = (
                self._connection.execute(
                    "SELECT * FROM units WHERE code = ?", (discipline["unit_code"],)
                ).fetchone()
                if discipline["unit_code"]
                else None
            )
            origin_units = tuple(
                self._connection.execute("SELECT * FROM units WHERE code = ?", (code_value,)).fetchone()
                for code_value in self._unit_codes(discipline)
            )
            if normalized_campus and not any(
                origin is not None and normalized_campus in normalize_text(origin["campus"] or "")
                for origin in origin_units
            ):
                continue
            if unit_code and unit_code not in self._unit_codes(discipline):
                continue
            if normalized_department and normalized_department not in normalize_text(
                discipline["department"] or ""
            ):
                continue
            professors = cast(tuple[dict[str, object], ...], bundle["professors"])
            if normalized_professor and not any(
                normalized_professor in str(item["normalized_name"]) for item in professors
            ):
                continue
            meetings = cast(tuple[Meeting, ...], bundle["meetings"])
            if not include_unknown and (
                bundle["schedule_status"] != "complete"
                or any(item.start_minute is None or item.end_minute is None for item in meetings)
            ):
                continue
            if day_set and not any(item.day in day_set for item in meetings):
                continue
            if window:
                block = Meeting("", window[0], window[1], None, None, "", "")
                matching = [
                    item
                    for item in meetings
                    if item.day
                    and conflict_between(
                        item,
                        Meeting(
                            item.day,
                            block.start_minute,
                            block.end_minute,
                            item.start_date,
                            item.end_date,
                            "",
                            "",
                        ),
                    )
                    is ConflictState.CONFLICT
                ]
                if window_mode == "contained":
                    if not meetings or not all(
                        item.start_minute is not None
                        and item.end_minute is not None
                        and item.start_minute >= window[0]
                        and item.end_minute <= window[1]
                        for item in meetings
                    ):
                        continue
                elif not matching:
                    continue
            item: dict[str, object] = {
                "code": code,
                "name": name,
                "department": discipline["department"],
                "unit_code": discipline["unit_code"],
                "unit_codes": self._unit_codes(discipline),
                "campus": unit["campus"] if unit else None,
                "source_campus_name": unit["source_campus_name"] if unit else None,
                "campus_provenance": unit["provenance"] if unit else None,
                "bundle": bundle,
            }
            candidates.append((score, str(bundle["id"]), item))
        candidates.sort(key=lambda value: (value[0], value[1]))
        if cursor_value:
            last_score = float(cast(float | int | str, cursor_value.get("score", 0)))
            last_id = str(cursor_value.get("last_id", ""))
            candidates = [item for item in candidates if (item[0], item[1]) > (last_score, last_id)]
        selected = candidates[:limit]
        next_cursor = (
            self.encode_cursor(selected[-1][0], selected[-1][1])
            if len(candidates) > limit and selected
            else None
        )
        return SearchPage(tuple(item[2] for item in selected), next_cursor)

    def get_discipline(self, code: str) -> dict[str, object] | None:
        row = self._connection.execute(
            "SELECT * FROM disciplines WHERE code = ?", (code.upper(),)
        ).fetchone()
        if row is None:
            return None
        versions = tuple(
            str(item[0])
            for item in self._connection.execute(
                "SELECT version FROM discipline_versions WHERE discipline_code = ? ORDER BY version",
                (row["code"],),
            ).fetchall()
        )
        version_records = tuple(
            dict(item)
            for item in self._connection.execute(
                "SELECT discipline_code, version, observed_at FROM discipline_versions "
                "WHERE discipline_code = ? ORDER BY version",
                (row["code"],),
            ).fetchall()
        )
        history = tuple(
            dict(item)
            for item in self._connection.execute(
                "SELECT * FROM offering_history WHERE discipline_code = ? ORDER BY period_code",
                (row["code"],),
            ).fetchall()
        )
        curricula = tuple(
            dict(item)
            for item in self._connection.execute(
                "SELECT c.id, c.course_code, c.habilitation_code, c.name, ci.ideal_period, ci.item_type "
                "FROM curricula c JOIN curriculum_items ci ON ci.curriculum_id = c.id "
                "WHERE ci.discipline_code = ? ORDER BY c.id, ci.ideal_period",
                (row["code"],),
            ).fetchall()
        )
        section_links = tuple(
            dict(item)
            for item in self._connection.execute(
                "SELECT practice_section_id, theory_section_id FROM section_links "
                "WHERE practice_section_id IN "
                "(SELECT id FROM sections WHERE discipline_code = ?) ORDER BY practice_section_id",
                (row["code"],),
            ).fetchall()
        )
        return {
            "code": row["code"],
            "name": row["name"],
            "unit_code": row["unit_code"],
            "unit_codes": self._unit_codes(row),
            "department": row["department"],
            "aula_credits": row["aula_credits"],
            "work_credits": row["work_credits"],
            "objectives": row["objectives"],
            "summary": row["summary"],
            "is_stub": bool(row["is_stub"]),
            "versions": versions,
            "version_records": version_records,
            "bundles": self.all_bundles(str(row["code"])),
            "history": history,
            "curricula": curricula,
            "section_links": section_links,
        }

    def search_curricula(
        self,
        query: str | None = None,
        *,
        unit_code: str | None = None,
        campus: str | None = None,
    ) -> tuple[dict[str, object], ...]:
        rows = self._connection.execute("SELECT * FROM curricula ORDER BY id").fetchall()
        normalized = normalize_text(query or "")
        normalized_campus = normalize_text(campus or "")
        return tuple(
            dict(row)
            for row in rows
            if (not normalized or normalized in normalize_text(f"{row['id']} {row['course_code']} {row['name']}"))
            and (not unit_code or row["unit_code"] == unit_code)
            and (not normalized_campus or normalized_campus in normalize_text(row["campus"] or ""))
        )

    def get_curriculum(self, curriculum_id: str) -> dict[str, object] | None:
        row = self._connection.execute(
            "SELECT * FROM curricula WHERE id = ?", (curriculum_id,)
        ).fetchone()
        if row is None:
            return None
        item_values: list[dict[str, object]] = []
        rows = self._connection.execute(
            "SELECT * FROM curriculum_items WHERE curriculum_id = ? ORDER BY ideal_period, id",
            (curriculum_id,),
        ).fetchall()
        for item in rows:
            value = dict(item)
            prerequisites: dict[str, list[str]] = {"weak": [], "strong": [], "set": []}
            for prerequisite in self._connection.execute(
                "SELECT relation, prerequisite_code FROM prerequisites WHERE curriculum_item_id = ? ORDER BY relation, prerequisite_code",
                (item["id"],),
            ).fetchall():
                prerequisites[str(prerequisite["relation"])].append(
                    str(prerequisite["prerequisite_code"])
                )
            value["prerequisites"] = prerequisites
            value["has_current_offer"] = self._connection.execute(
                "SELECT 1 FROM bundles WHERE discipline_code = ? AND selectable = 1 LIMIT 1",
                (item["discipline_code"],),
            ).fetchone() is not None
            item_values.append(value)
        return {
            "id": row["id"],
            "course_code": row["course_code"],
            "habilitation_code": row["habilitation_code"],
            "name": row["name"],
            "unit_code": row["unit_code"],
            "campus": row["campus"],
            "period_code": row["period_code"],
            "items": tuple(item_values),
        }
