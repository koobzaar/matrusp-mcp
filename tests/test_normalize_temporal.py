from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from matrusp_mcp.domain import ConflictState, Meeting
from matrusp_mcp.normalize import normalize_text, parse_time
from matrusp_mcp.temporal import conflict_between, conflicts, normalized_union


def meeting(
    day: str = "mon",
    start: int | None = 600,
    end: int | None = 720,
    first: date | None = date(2026, 8, 1),
    last: date | None = date(2026, 12, 20),
) -> Meeting:
    return Meeting(
        day=day,
        start_minute=start,
        end_minute=end,
        start_date=first,
        end_date=last,
        start_text="10:00" if start is not None else "",
        end_text="12:00" if end is not None else "",
    )


def test_unicode_normalization_keeps_original_outside_normalizer() -> None:
    assert normalize_text("  Introdução  à   Computação ") == "introducao a computacao"
    assert normalize_text("PROGRAMAÇÃO") == "programacao"
    assert parse_time("23:59") == 1439
    assert parse_time("25:00") is None
    assert parse_time("bad") is None


def test_half_open_boundaries_and_inclusive_dates() -> None:
    assert (
        conflict_between(meeting(end=720), meeting(start=720, end=840)) == ConflictState.NO_CONFLICT
    )
    assert conflict_between(meeting(end=721), meeting(start=720, end=840)) == ConflictState.CONFLICT
    assert (
        conflict_between(
            meeting(first=date(2026, 8, 1), last=date(2026, 8, 10)),
            meeting(first=date(2026, 8, 10), last=date(2026, 8, 20)),
        )
        == ConflictState.CONFLICT
    )


def test_disjoint_dates_and_incomplete_data() -> None:
    assert (
        conflict_between(
            meeting(first=date(2026, 8, 1), last=date(2026, 8, 9)),
            meeting(first=date(2026, 8, 10), last=date(2026, 8, 20)),
        )
        == ConflictState.NO_CONFLICT
    )
    assert conflict_between(meeting(start=None), meeting()) == ConflictState.UNKNOWN
    assert conflict_between(meeting(day="unknown"), meeting()) == ConflictState.UNKNOWN
    assert (
        conflict_between(
            meeting(first=date(2026, 8, 1), last=None),
            meeting(first=date(2026, 8, 2), last=date(2026, 8, 3)),
        )
        == ConflictState.UNKNOWN
    )
    assert conflict_between(meeting(start=720, end=600), meeting()) == ConflictState.UNKNOWN
    assert conflicts([meeting(start=None)], [meeting()]) == ConflictState.UNKNOWN


@given(st.sampled_from(["mon", "tue", "wed", "thu", "fri", "sat", "sun"]), st.integers(0, 1300))
def test_conflict_is_symmetric(day: str, start: int) -> None:
    left = meeting(day=day, start=start, end=start + 60)
    right = meeting(day=day, start=start + 30, end=start + 90)
    assert conflict_between(left, right) == conflict_between(right, left)


def test_union_is_idempotent_order_independent_and_preserves_ranges() -> None:
    first = meeting(start=600, end=720)
    contained = meeting(start=630, end=690)
    overlap = meeting(start=700, end=780)
    other_dates = meeting(start=600, end=660, first=date(2027, 1, 1), last=date(2027, 2, 1))
    expected = normalized_union([first, contained, overlap, other_dates])
    assert expected == normalized_union([other_dates, overlap, first, contained, first])
    assert len(expected) == 2
    assert (expected[0].start_minute, expected[0].end_minute) == (600, 780)
