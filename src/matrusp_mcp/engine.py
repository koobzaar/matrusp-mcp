"""Backtracking determinístico e ranking de grades."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import cast

from .domain import Block, Bundle, ConflictState, GenerationResult, RankedSchedule, ScheduleMetrics
from .temporal import conflicts, normalized_union


@dataclass(frozen=True, slots=True)
class Preferences:
    days_weight: int = 1
    gaps_weight: int = 1
    outside_preferred_windows_weight: int = 0
    avoided_professors_weight: int = 0
    preferred_professors_weight: int = 0
    avoided_professors: tuple[str, ...] = ()
    preferred_professors: tuple[str, ...] = ()
    preferred_windows: tuple[tuple[str, int, int], ...] = ()

    def __post_init__(self) -> None:
        for value in (
            self.days_weight,
            self.gaps_weight,
            self.outside_preferred_windows_weight,
            self.avoided_professors_weight,
            self.preferred_professors_weight,
        ):
            if not 0 <= value <= 100:
                raise ValueError("preference weights must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    required_disciplines: tuple[str, ...]
    max_results: int = 10
    node_budget: int = 1_000_000
    existing_bundles: tuple[Bundle, ...] = ()
    blocks: tuple[Block, ...] = ()
    preferences: Preferences = Preferences()
    hard_constraints: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 1 <= len(self.required_disciplines) <= 15:
            raise ValueError("up to 15 disciplines are supported")
        if len(set(self.required_disciplines)) != len(self.required_disciplines):
            raise ValueError("required disciplines must be unique")
        if not 1 <= self.max_results <= 50 or self.node_budget < 1:
            raise ValueError("invalid generation limits")


def _metrics(
    selected: tuple[Bundle, ...], preferences: Preferences
) -> tuple[float, ScheduleMetrics]:
    meetings = [meeting for bundle in selected for meeting in bundle.meetings]
    union = normalized_union(meetings)
    active_days = len({meeting.day for meeting in union})
    gap_minutes = 0
    by_day: dict[str, list[tuple[int, int]]] = {}
    for meeting in union:
        if meeting.start_minute is not None and meeting.end_minute is not None:
            by_day.setdefault(meeting.day, []).append((meeting.start_minute, meeting.end_minute))
    for ranges in by_day.values():
        ranges.sort()
        gap_minutes += sum(
            max(0, start - previous_end)
            for (_, previous_end), (start, _) in zip(ranges, ranges[1:])
        )
    outside = 0.0
    if preferences.preferred_windows:
        for meeting in union:
            if meeting.start_minute is None or meeting.end_minute is None:
                continue
            windows = [
                (start, end)
                for day, start, end in preferences.preferred_windows
                if day == meeting.day
            ]
            if not windows or not any(
                meeting.start_minute >= start and meeting.end_minute <= end
                for start, end in windows
            ):
                outside += (meeting.end_minute - meeting.start_minute) / 60
    professor_names = {
        professor.normalized_name for bundle in selected for professor in bundle.professors
    }
    avoided = len(professor_names.intersection(preferences.avoided_professors))
    preferred = len(professor_names.intersection(preferences.preferred_professors))
    metrics = ScheduleMetrics(active_days, gap_minutes / 60, outside, avoided, preferred)
    score = (
        preferences.days_weight * metrics.active_days
        + preferences.gaps_weight * metrics.total_gap_hours
        + preferences.outside_preferred_windows_weight * metrics.hours_outside_preferred_windows
        + preferences.avoided_professors_weight * metrics.avoided_professor_matches
        - preferences.preferred_professors_weight * metrics.preferred_professor_matches
    )
    return score, metrics


def generate_schedules(
    request: GenerationRequest, candidates: Mapping[str, Iterable[Bundle]]
) -> GenerationResult:
    normalized: dict[str, tuple[Bundle, ...]] = {}
    discard: dict[str, int] = {"conflict": 0, "quality": 0, "unknown": 0}
    for discipline in sorted(set(request.required_disciplines)):
        values = tuple(
            sorted(
                (
                    bundle
                    for bundle in candidates.get(discipline, ())
                    if bundle.selectable and bundle.schedule_status == "complete"
                ),
                key=lambda item: item.id,
            )
        )
        if not values:
            discard["quality"] += 1
        normalized[discipline] = values[:100]
    order = tuple(sorted(normalized, key=lambda code: (len(normalized[code]), code)))
    candidates_by_id = {
        bundle.id: bundle for values in normalized.values() for bundle in values
    }
    conflict_graph: dict[tuple[str, str], ConflictState] = {}
    candidate_values = tuple(sorted(candidates_by_id.values(), key=lambda item: item.id))
    for left_index, left in enumerate(candidate_values):
        for right in candidate_values[left_index + 1 :]:
            conflict_graph[(left.id, right.id)] = conflicts(left.meetings, right.meetings)

    def graph_state(left: Bundle, right: Bundle) -> ConflictState:
        if left.id == right.id:
            return ConflictState.CONFLICT
        key = (left.id, right.id) if left.id < right.id else (right.id, left.id)
        return conflict_graph.get(key, conflicts(left.meetings, right.meetings))

    block_meetings = tuple(block.meeting for block in request.blocks)
    found: list[RankedSchedule] = []
    explored = 0
    truncated = False

    initial = tuple(request.existing_bundles)

    def walk(index: int, selected: tuple[Bundle, ...]) -> None:
        nonlocal explored, truncated
        if explored >= request.node_budget:
            truncated = True
            return
        explored += 1
        if index == len(order):
            score, metrics = _metrics(selected, request.preferences)
            max_active_days = request.hard_constraints.get("max_active_days")
            max_gap_hours = request.hard_constraints.get("max_total_gap_hours")
            required_days = request.hard_constraints.get("required_days")
            if max_active_days is not None and metrics.active_days > int(cast(int, max_active_days)):
                discard["hard_constraint"] = discard.get("hard_constraint", 0) + 1
                return
            if max_gap_hours is not None and metrics.total_gap_hours > float(cast(float, max_gap_hours)):
                discard["hard_constraint"] = discard.get("hard_constraint", 0) + 1
                return
            if required_days:
                required = (
                    {str(value) for value in required_days}
                    if isinstance(required_days, (list, tuple, set))
                    else set()
                )
                active_days = {meeting.day for bundle in selected for meeting in bundle.meetings}
                if not required.issubset(active_days):
                    discard["hard_constraint"] = discard.get("hard_constraint", 0) + 1
                    return
            ranked = RankedSchedule(tuple(bundle.id for bundle in selected), score, metrics)
            position = bisect_right(
                found,
                (ranked.score, ranked.bundle_ids),
                key=lambda item: (item.score, item.bundle_ids),
            )
            found.insert(position, ranked)
            if len(found) > request.max_results:
                found.pop()
            return
        discipline = order[index]
        for candidate in normalized[discipline]:
            state = conflicts(candidate.meetings, block_meetings)
            for selected_bundle in selected:
                pair_state = graph_state(candidate, selected_bundle)
                if pair_state is ConflictState.CONFLICT:
                    state = pair_state
                    break
                if pair_state is ConflictState.UNKNOWN and state is ConflictState.NO_CONFLICT:
                    state = pair_state
            if state is ConflictState.CONFLICT:
                discard["conflict"] += 1
                continue
            if state is ConflictState.UNKNOWN:
                discard["unknown"] += 1
                continue
            walk(index + 1, selected + (candidate,))

    existing_quality = any(
        not bundle.selectable or bundle.schedule_status != "complete" for bundle in initial
    )
    existing_state = conflicts(
        [meeting for bundle in initial for meeting in bundle.meetings], block_meetings
    )
    if existing_state is ConflictState.NO_CONFLICT:
        for left_index, left in enumerate(initial):
            for right in initial[left_index + 1 :]:
                pair_state = graph_state(left, right)
                if pair_state is ConflictState.CONFLICT:
                    existing_state = pair_state
                    break
                if pair_state is ConflictState.UNKNOWN:
                    existing_state = pair_state
            if existing_state is not ConflictState.NO_CONFLICT:
                break
    if existing_quality:
        discard["quality"] += 1
    elif existing_state is ConflictState.CONFLICT:
        discard["conflict"] += 1
    elif existing_state is ConflictState.UNKNOWN:
        discard["unknown"] += 1
    else:
        walk(0, initial)
    return GenerationResult(
        tuple(found), truncated, explored, {key: value for key, value in discard.items() if value}
    )
