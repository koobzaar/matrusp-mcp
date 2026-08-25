"""Casos de uso públicos; nenhum deles acessa a rede ou grava no disco."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, cast

from .api_models import (
    CheckConflictsInput,
    CompareSchedulesInput,
    FindGapFillersInput,
    GenerateSchedulesInput,
    GetCurriculumInput,
    GetDisciplineInput,
    PreferencesInput,
    PublicResponse,
    SearchCurriculaInput,
    SearchOfferingsInput,
)
from .domain import Block, Bundle, ConflictState, Meeting, Professor
from .engine import GenerationRequest, Preferences, _metrics, generate_schedules
from .normalize import normalize_day, normalize_text, parse_time
from .repository import Repository, SearchTooBroadError, StaleCursorError
from .temporal import conflict_between, conflicts


class PublicError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _time(value: str | None) -> int | None:
    result = parse_time(value)
    if value is not None and result is None:
        raise PublicError("invalid_input", f"invalid time: {value}")
    return result


def _date(value: object, field: str) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise PublicError("invalid_input", f"invalid {field}: {value}") from error


def _manual_blocks(values: list[dict[str, Any]]) -> tuple[Block, ...]:
    blocks: list[Block] = []
    for index, value in enumerate(values):
        day = normalize_day(str(value.get("day", "")))
        start_text = value.get("start_time")
        end_text = value.get("end_time")
        start = _time(str(start_text)) if start_text is not None else None
        end = _time(str(end_text)) if end_text is not None else None
        start_date = _date(value.get("start_date"), "start_date")
        end_date = _date(value.get("end_date"), "end_date")
        if day is None or start is None or end is None or end <= start:
            raise PublicError("invalid_input", "manual blocks require a valid day and interval")
        if start_date is not None and end_date is not None and end_date < start_date:
            raise PublicError("invalid_input", "manual block dates must be inclusive and ordered")
        blocks.append(
            Block(
                str(value.get("id") or f"block:{index}"),
                Meeting(
                    day,
                    start,
                    end,
                    start_date,
                    end_date,
                    str(start_text),
                    str(end_text),
                    str(value.get("day", "")),
                ),
            )
        )
    return tuple(blocks)


def _bundle(value: dict[str, object]) -> Bundle:
    section_ids = cast(tuple[object, ...], value["section_ids"])
    meetings = cast(tuple[Meeting, ...], value["meetings"])
    professors = cast(tuple[dict[str, object], ...], value["professors"])
    flags = cast(list[object], value["data_quality_flags"])
    return Bundle(
        id=str(value["id"]),
        discipline_code=str(value["discipline_code"]),
        section_ids=tuple(str(item) for item in section_ids),
        meetings=meetings,
        professors=tuple(
            Professor(
                str(item["display_name"]), str(item["normalized_name"]), bool(item["responsible"])
            )
            for item in professors
        ),
        selectable=bool(value["selectable"]),
        schedule_status=str(value["schedule_status"]),
        data_quality_flags=tuple(str(item) for item in flags),
    )


def _public_item(value: object) -> object:
    if isinstance(value, Meeting):
        return {
            "day": value.day,
            "start_minute": value.start_minute,
            "end_minute": value.end_minute,
            "start_date": value.start_date.isoformat() if value.start_date else None,
            "end_date": value.end_date.isoformat() if value.end_date else None,
            "start_text": value.start_text,
            "end_text": value.end_text,
            "original_day": value.original_day,
        }
    if isinstance(value, tuple):
        return [_public_item(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _public_item(item) for key, item in value.items()}
    return value


def _quality_warnings(value: object) -> list[str]:
    warnings: set[str] = set()
    if isinstance(value, dict):
        flags = value.get("data_quality_flags")
        if isinstance(flags, (list, tuple)):
            warnings.update(str(flag) for flag in flags)
        if value.get("schedule_status") in {"partial", "unknown"}:
            warnings.add(f"schedule_{value['schedule_status']}")
        if value.get("is_stub") is True:
            warnings.add("discipline_stub_without_rich_details")
        for item in value.values():
            warnings.update(_quality_warnings(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            warnings.update(_quality_warnings(item))
    return sorted(warnings)


class Service:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    @classmethod
    def from_path(cls, path: str | Path) -> Service:
        return cls(Repository(Path(path)))

    def _response(self, data: dict[str, Any], warnings: list[str] | None = None) -> PublicResponse:
        combined = sorted(set((warnings or []) + _quality_warnings(data)))
        return PublicResponse(
            snapshot_id=self.repository.snapshot_id,
            observed_at=self.repository.observed_at,
            warnings=combined,
            data=cast(dict[str, Any], _public_item(data)),
        )

    def search_offerings(self, request: SearchOfferingsInput) -> PublicResponse:
        start, end = _time(request.start_time), _time(request.end_time)
        if (start is None) != (end is None) or (
            start is not None and end is not None and end <= start
        ):
            raise PublicError(
                "invalid_input", "start_time and end_time must form a positive interval"
            )
        try:
            page = self.repository.search_offerings(
                query=request.query,
                professor=request.professor,
                campus=request.campus,
                unit_code=request.unit_code,
                department=request.department,
                days=tuple(request.days),
                window=(start, end) if start is not None and end is not None else None,
                window_mode=request.window_mode,
                include_unknown=request.include_unknown,
                limit=request.limit,
                cursor=request.cursor,
            )
        except StaleCursorError as error:
            raise PublicError("stale_cursor", str(error)) from error
        except SearchTooBroadError as error:
            raise PublicError("search_too_broad", str(error)) from error
        return self._response({"items": page.items, "next_cursor": page.next_cursor})

    def get_discipline(self, request: GetDisciplineInput) -> PublicResponse:
        data = self.repository.get_discipline(request.code)
        if data is None:
            raise PublicError("not_found", f"discipline not found: {request.code}")
        return self._response(data)

    def _selected_meetings(
        self, bundle_ids: list[str], section_ids: list[str]
    ) -> tuple[Meeting, ...]:
        result: list[Meeting] = []
        for bundle_id in bundle_ids:
            bundle = self.repository.get_bundle(bundle_id)
            if bundle is None:
                raise PublicError("not_found", f"bundle not found: {bundle_id}")
            result.extend(cast(tuple[Meeting, ...], bundle["meetings"]))
        for section_id in section_ids:
            meetings = self.repository.get_section_meetings(section_id)
            if not meetings and not self.repository.has_section(section_id):
                raise PublicError("not_found", f"section not found: {section_id}")
            result.extend(meetings)
        return tuple(result)

    def find_gap_fillers(self, request: FindGapFillersInput) -> PublicResponse:
        day = normalize_day(request.day)
        start, end = _time(request.start_time), _time(request.end_time)
        if day is None or start is None or end is None or end <= start:
            raise PublicError("invalid_input", "invalid gap window")
        selected = self._selected_meetings(request.bundle_ids, request.section_ids)
        block = Meeting(day, start, end, None, None, request.start_time, request.end_time)
        items: list[dict[str, object]] = []
        for value in self.repository.all_bundles(selectable_only=not request.include_unknown):
            meetings = cast(tuple[Meeting, ...], value["meetings"])
            if not request.include_unknown and value["schedule_status"] != "complete":
                continue
            state = conflicts(meetings, selected)
            if state is ConflictState.UNKNOWN or state is ConflictState.CONFLICT:
                continue
            if request.window_mode == "contained":
                fits = bool(meetings) and all(
                    meeting.day == day
                    and meeting.start_minute is not None
                    and meeting.end_minute is not None
                    and start <= meeting.start_minute
                    and meeting.end_minute <= end
                    for meeting in meetings
                )
            else:
                fits = any(
                    conflict_between(meeting, block) is ConflictState.CONFLICT
                    for meeting in meetings
                )
            if fits:
                items.append(value)
        return self._response({"items": items})

    def check_schedule_conflicts(self, request: CheckConflictsInput) -> PublicResponse:
        bundle_ids = list(request.bundle_ids)
        section_ids = list(request.section_ids)
        blocks = list(request.blocks)
        for item in request.items:
            if "bundle_id" in item:
                bundle_ids.append(str(item["bundle_id"]))
            elif "section_id" in item:
                section_ids.append(str(item["section_id"]))
            elif "block" in item and isinstance(item["block"], dict):
                blocks.append(cast(dict[str, Any], item["block"]))
            elif item:
                raise PublicError("invalid_input", "conflict items require bundle_id, section_id, or block")
        items: list[tuple[str, tuple[Meeting, ...]]] = []
        for bundle_id in bundle_ids:
            bundle = self.repository.get_bundle(bundle_id)
            if bundle is None:
                raise PublicError("not_found", f"bundle not found: {bundle_id}")
            items.append((bundle_id, cast(tuple[Meeting, ...], bundle["meetings"])))
        for section_id in section_ids:
            meetings = self.repository.get_section_meetings(section_id)
            if not meetings and not self.repository.has_section(section_id):
                raise PublicError("not_found", f"section not found: {section_id}")
            items.append((section_id, meetings))
        items.extend((block.id, (block.meeting,)) for block in _manual_blocks(blocks))
        pairs: list[dict[str, object]] = []
        unknown_pairs: list[dict[str, str]] = []
        state = ConflictState.NO_CONFLICT
        for index, (left_id, left) in enumerate(items):
            if not left:
                state = ConflictState.UNKNOWN
            for right_id, right in items[index + 1 :]:
                result = conflicts(left, right)
                if result is ConflictState.CONFLICT:
                    state = result
                    responsible = [
                        (left_meeting, right_meeting)
                        for left_meeting in left
                        for right_meeting in right
                        if conflict_between(left_meeting, right_meeting)
                        is ConflictState.CONFLICT
                    ]
                    pairs.append(
                        {
                            "left": left_id,
                            "right": right_id,
                            "meetings": [
                                {"left": pair[0], "right": pair[1]} for pair in responsible
                            ],
                        }
                    )
                elif result is ConflictState.UNKNOWN and state is ConflictState.NO_CONFLICT:
                    state = result
                    unknown_pairs.append({"left": left_id, "right": right_id})
                elif result is ConflictState.UNKNOWN:
                    unknown_pairs.append({"left": left_id, "right": right_id})
        return self._response(
            {"state": state.value, "conflicts": pairs, "unknown_pairs": unknown_pairs},
            ["schedule_unknown"] if state is ConflictState.UNKNOWN else None,
        )

    def _preferences(self, value: PreferencesInput) -> Preferences:
        windows_list: list[tuple[str, int, int]] = []
        for item in value.preferred_windows:
            day = normalize_day(str(item.get("day", "")))
            start_value, end_value = item.get("start_time"), item.get("end_time")
            start = _time(str(start_value)) if start_value is not None else None
            end = _time(str(end_value)) if end_value is not None else None
            if day is None or start is None or end is None or end <= start:
                raise PublicError("invalid_input", "preferred windows require valid intervals")
            windows_list.append((day, start, end))
        windows = tuple(windows_list)
        return Preferences(
            value.days_weight,
            value.gaps_weight,
            value.outside_preferred_windows_weight
            or (1 if value.preferred_windows else 0),
            value.avoided_professors_weight or (1 if value.avoided_professors else 0),
            value.preferred_professors_weight or (1 if value.preferred_professors else 0),
            tuple(normalize_text(item) for item in value.avoided_professors),
            tuple(normalize_text(item) for item in value.preferred_professors),
            windows,
        )

    def generate_schedules(self, request: GenerateSchedulesInput) -> PublicResponse:
        required_disciplines = tuple(code.strip().upper() for code in request.required_disciplines)
        all_values = {
            str(item["id"]): _bundle(item)
            for item in self.repository.all_bundles(selectable_only=True)
        }
        unknown_allowed = sorted(set(request.allowed_bundle_ids) - set(all_values))
        if unknown_allowed:
            raise PublicError("not_found", f"bundle not found: {unknown_allowed[0]}")
        unknown_existing = sorted(set(request.existing_bundle_ids) - set(all_values))
        if unknown_existing:
            raise PublicError("not_found", f"bundle not found: {unknown_existing[0]}")
        if request.allowed_bundle_ids:
            allowed = {
                bundle_id: all_values[bundle_id]
                for bundle_id in request.allowed_bundle_ids
                if bundle_id in all_values
            }
        else:
            allowed = all_values
        candidates: dict[str, list[Bundle]] = {}
        for discipline in required_disciplines:
            if self.repository.get_discipline(discipline) is None:
                raise PublicError("not_found", f"discipline not found: {discipline}")
            candidates[discipline] = [
                value for value in allowed.values() if value.discipline_code == discipline
            ]
        existing = tuple(all_values[bundle_id] for bundle_id in request.existing_bundle_ids)
        hard = dict(request.hard_constraints)
        forbidden_days = {
            day
            for item in cast(list[Any], hard.get("forbidden_days", []))
            if (day := normalize_day(str(item))) is not None
        }
        if forbidden_days:
            candidates = {
                discipline: [
                    value
                    for value in values
                    if not any(meeting.day in forbidden_days for meeting in value.meetings)
                ]
                for discipline, values in candidates.items()
            }
        required_days_value = hard.get("required_days")
        if required_days_value is not None:
            if not isinstance(required_days_value, list):
                raise PublicError("invalid_input", "required_days must be a list")
            required_days: list[str] = []
            for value in required_days_value:
                normalized_day = normalize_day(str(value))
                if normalized_day is None:
                    raise PublicError("invalid_input", f"invalid required day: {value}")
                required_days.append(normalized_day)
            hard["required_days"] = required_days
        result = generate_schedules(
            GenerationRequest(
                required_disciplines,
                request.max_results,
                request.node_budget,
                existing,
                _manual_blocks(request.blocks),
                self._preferences(request.preferences),
                hard,
            ),
            candidates,
        )
        return self._response(
            {
                "schedules": [asdict(item) for item in result.schedules],
                "truncated": result.truncated,
                "explored_nodes": result.explored_nodes,
                "discard_reasons": result.discard_reasons,
            },
            ["schedule_unknown"] if result.discard_reasons.get("unknown") else None,
        )

    def compare_schedules(self, request: CompareSchedulesInput) -> PublicResponse:
        results: list[dict[str, object]] = []
        blocks = _manual_blocks(request.blocks)
        preferences = self._preferences(request.preferences)
        for alternative in request.alternatives:
            bundles = []
            for bundle_id in alternative:
                value = self.repository.get_bundle(bundle_id)
                if value is None:
                    raise PublicError("not_found", f"bundle not found: {bundle_id}")
                bundles.append(_bundle(value))
            state = ConflictState.NO_CONFLICT
            selected: list[Meeting] = [block.meeting for block in blocks]
            for bundle in bundles:
                result = conflicts(bundle.meetings, selected)
                if result is ConflictState.CONFLICT:
                    state = result
                    break
                if result is ConflictState.UNKNOWN:
                    state = result
                selected.extend(bundle.meetings)
            score, metrics = _metrics(tuple(bundles), preferences)
            results.append(
                {
                    "bundle_ids": alternative,
                    "state": state.value,
                    "score": score,
                    "metrics": asdict(metrics),
                }
            )
        return self._response({"alternatives": results})

    def search_curricula(self, request: SearchCurriculaInput) -> PublicResponse:
        values = self.repository.search_curricula(
            request.query, unit_code=request.unit_code, campus=request.campus
        )
        return self._response({"items": values[: request.limit]})

    def get_curriculum(self, request: GetCurriculumInput) -> PublicResponse:
        value = self.repository.get_curriculum(request.curriculum_id)
        if value is None:
            raise PublicError("not_found", f"curriculum not found: {request.curriculum_id}")
        return self._response(value)
