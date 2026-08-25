"""Operações temporais puras e determinísticas."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import date

from .domain import ConflictState, Meeting


def _date_overlap(left: Meeting, right: Meeting) -> bool | None:
    if (left.start_date is None and left.end_date is None) or (
        right.start_date is None and right.end_date is None
    ):
        return True
    if None in (left.start_date, left.end_date, right.start_date, right.end_date):
        return None
    assert left.start_date is not None and left.end_date is not None
    assert right.start_date is not None and right.end_date is not None
    return max(left.start_date, right.start_date) <= min(left.end_date, right.end_date)


def conflict_between(left: Meeting, right: Meeting) -> ConflictState:
    if left.day in {"", "unknown"} or right.day in {"", "unknown"}:
        return ConflictState.UNKNOWN
    if left.day != right.day:
        return ConflictState.NO_CONFLICT
    dates = _date_overlap(left, right)
    if dates is False:
        return ConflictState.NO_CONFLICT
    if (
        dates is None
        or left.start_minute is None
        or left.end_minute is None
        or right.start_minute is None
        or right.end_minute is None
    ):
        return ConflictState.UNKNOWN
    if left.end_minute <= left.start_minute or right.end_minute <= right.start_minute:
        return ConflictState.UNKNOWN
    if max(left.start_minute, right.start_minute) < min(left.end_minute, right.end_minute):
        return ConflictState.CONFLICT
    return ConflictState.NO_CONFLICT


def conflicts(left: Iterable[Meeting], right: Iterable[Meeting]) -> ConflictState:
    saw_unknown = False
    for first in left:
        for second in right:
            state = conflict_between(first, second)
            if state is ConflictState.CONFLICT:
                return state
            if state is ConflictState.UNKNOWN:
                saw_unknown = True
    return ConflictState.UNKNOWN if saw_unknown else ConflictState.NO_CONFLICT


def normalized_union(meetings: Iterable[Meeting]) -> tuple[Meeting, ...]:
    unique = sorted(
        set(meetings),
        key=lambda item: (
            item.day,
            item.start_date or date.min,
            item.end_date or date.max,
            item.start_minute if item.start_minute is not None else -1,
            item.end_minute if item.end_minute is not None else -1,
        ),
    )
    result: list[Meeting] = []
    for item in unique:
        if not result:
            result.append(item)
            continue
        previous = result[-1]
        same_range = (
            previous.day == item.day
            and previous.start_date == item.start_date
            and previous.end_date == item.end_date
        )
        if (
            same_range
            and previous.end_minute is not None
            and item.start_minute is not None
            and previous.end_minute >= item.start_minute
        ):
            end = max(previous.end_minute or item.end_minute or 0, item.end_minute or 0)
            result[-1] = replace(
                previous, end_minute=end, end_text=item.end_text or previous.end_text
            )
        else:
            result.append(item)
    return tuple(result)
