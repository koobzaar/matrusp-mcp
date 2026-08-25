from datetime import date
from itertools import product

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from matrusp_mcp.bundles import derive_bundles
from matrusp_mcp.domain import Bundle, Meeting, Professor, Section
from matrusp_mcp.engine import GenerationRequest, Preferences, generate_schedules


def section(
    discipline: str,
    code: str,
    day: str,
    start: int,
    end: int,
    *,
    theory: str | None = None,
    schedule_status: str = "complete",
) -> Section:
    return Section(
        id=f"section:{discipline}:{code}",
        discipline_code=discipline,
        section_code=code,
        period_code="20262",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 12, 20),
        section_type="Teórica" if theory is None else "Prática",
        notes="",
        schedule_status=schedule_status,
        meetings=(
            Meeting(
                day=day,
                start_minute=start,
                end_minute=end,
                start_date=date(2026, 8, 1),
                end_date=date(2026, 12, 20),
                start_text="",
                end_text="",
            ),
        ),
        professors=(Professor.from_source("(R) Ada Lovelace"),),
        linked_theory_section_code=theory,
    )


def test_theory_practice_bundles_have_stable_ids_and_orphans_are_not_selectable() -> None:
    sections = [
        section("MAC0001", "T01", "mon", 600, 720),
        section("MAC0001", "P01", "wed", 600, 720, theory="T01"),
        section("MAC0001", "P02", "fri", 600, 720, theory="T01"),
        section("MAC0001", "P99", "tue", 600, 720, theory="MISSING"),
    ]
    bundles = derive_bundles(sections)
    assert [bundle.id for bundle in bundles] == [
        "bundle:MAC0001:T01+P01",
        "bundle:MAC0001:T01+P02",
        "bundle:MAC0001:P99",
    ]
    assert bundles[-1].selectable is False
    assert bundles[-1].data_quality_flags == ("orphan_practice_link",)
    assert len(bundles[0].meetings) == 2


def bundle(discipline: str, suffix: str, day: str, start: int, end: int) -> Bundle:
    source = section(discipline, suffix, day, start, end)
    return Bundle(
        id=f"bundle:{discipline}:{suffix}",
        discipline_code=discipline,
        section_ids=(source.id,),
        meetings=source.meetings,
        professors=source.professors,
        selectable=True,
        schedule_status="complete",
    )


def test_generator_prunes_conflicts_ranks_and_breaks_ties_lexicographically() -> None:
    candidates = {
        "A": [bundle("A", "1", "mon", 480, 600), bundle("A", "2", "tue", 480, 600)],
        "B": [bundle("B", "1", "mon", 540, 660), bundle("B", "2", "wed", 480, 600)],
    }
    result = generate_schedules(
        GenerationRequest(required_disciplines=("A", "B"), max_results=10), candidates
    )
    assert [item.bundle_ids for item in result.schedules] == [
        ("bundle:A:1", "bundle:B:2"),
        ("bundle:A:2", "bundle:B:1"),
        ("bundle:A:2", "bundle:B:2"),
    ]
    assert result.schedules[0].metrics.active_days == 2
    assert result.explored_nodes > 0
    assert result.discard_reasons["conflict"] == 1


def test_generator_keeps_only_the_best_result_with_deterministic_ties() -> None:
    candidates = {
        code: [
            bundle(code, suffix, day, 600, 660)
            for suffix, day in (("3", "wed"), ("1", "mon"), ("2", "tue"))
        ]
        for code in ("A", "B")
    }
    result = generate_schedules(
        GenerationRequest(
            required_disciplines=("A", "B"),
            max_results=1,
            preferences=Preferences(days_weight=0, gaps_weight=0),
        ),
        candidates,
    )
    assert [item.bundle_ids for item in result.schedules] == [
        ("bundle:A:1", "bundle:B:2")
    ]
    assert result.truncated is False


def test_generator_budget_returns_deterministic_partial_results() -> None:
    candidates = {
        code: [bundle(code, str(index), "mon", index * 120, index * 120 + 60) for index in range(4)]
        for code in ("A", "B", "C")
    }
    request = GenerationRequest(required_disciplines=("A", "B", "C"), max_results=5, node_budget=7)
    first = generate_schedules(request, candidates)
    second = generate_schedules(request, candidates)
    assert first == second
    assert first.truncated is True
    assert first.explored_nodes == 7


def test_generator_limits_and_quality_discards() -> None:
    with pytest.raises(ValueError):
        Preferences(days_weight=101)
    with pytest.raises(ValueError):
        GenerationRequest(required_disciplines=())
    with pytest.raises(ValueError):
        GenerationRequest(required_disciplines=("A",), max_results=0)
    with pytest.raises(ValueError):
        GenerationRequest(required_disciplines=("A", "A"))
    result = generate_schedules(GenerationRequest(required_disciplines=("MISSING",)), {})
    assert result.schedules == () and result.discard_reasons["quality"] == 1


def test_generator_preferences_and_existing_conflict_paths() -> None:
    candidate = bundle("A", "1", "mon", 600, 660)
    preferred = generate_schedules(
        GenerationRequest(
            required_disciplines=("A",),
            preferences=Preferences(
                outside_preferred_windows_weight=2,
                preferred_windows=(("tue", 600, 700),),
            ),
        ),
        {"A": [candidate]},
    )
    assert preferred.schedules[0].metrics.hours_outside_preferred_windows == 1
    conflict = generate_schedules(
        GenerationRequest(required_disciplines=("A",), existing_bundles=(candidate,)),
        {"A": [candidate]},
    )
    assert conflict.schedules == () and conflict.discard_reasons["conflict"] == 1


def test_generator_rejects_unknown_schedule_and_applies_hard_constraints() -> None:
    incomplete = Bundle(
        id="bundle:A:unknown",
        discipline_code="A",
        section_ids=(),
        meetings=(Meeting("unknown", None, None, None, None, "", ""),),
        professors=(),
        selectable=True,
        schedule_status="partial",
    )
    unknown = generate_schedules(
        GenerationRequest(required_disciplines=("A",)), {"A": [incomplete]}
    )
    assert unknown.schedules == () and unknown.discard_reasons["quality"] == 1
    existing_unknown = generate_schedules(
        GenerationRequest(required_disciplines=("A",), existing_bundles=(incomplete,)),
        {"A": []},
    )
    assert existing_unknown.schedules == () and existing_unknown.discard_reasons["quality"] == 2
    one = bundle("A", "one", "mon", 600, 660)
    two = bundle("B", "two", "tue", 600, 660)
    limited = generate_schedules(
        GenerationRequest(
            required_disciplines=("A", "B"),
            hard_constraints={"max_active_days": 1, "required_days": ["mon"]},
        ),
        {"A": [one], "B": [two]},
    )
    assert limited.schedules == () and limited.discard_reasons["hard_constraint"] == 1
    missing_required = generate_schedules(
        GenerationRequest(
            required_disciplines=("A",), hard_constraints={"required_days": ["wed"]}
        ),
        {"A": [one]},
    )
    assert missing_required.schedules == ()
    gap = bundle("B", "gap", "mon", 720, 780)
    gap_result = generate_schedules(
        GenerationRequest(
            required_disciplines=("A", "B"), hard_constraints={"max_total_gap_hours": 0}
        ),
        {"A": [one], "B": [gap]},
    )
    assert gap_result.schedules == ()


def test_generator_handles_unknown_pairs_existing_pairs_and_incomplete_metrics() -> None:
    unknown = Bundle(
        id="bundle:A:unknown-pair",
        discipline_code="A",
        section_ids=(),
        meetings=(Meeting("unknown", 600, 660, None, None, "", ""),),
        professors=(),
        selectable=True,
        schedule_status="complete",
    )
    valid = bundle("B", "valid", "mon", 600, 660)
    result = generate_schedules(
        GenerationRequest(required_disciplines=("A", "B")),
        {"A": [unknown], "B": [valid]},
    )
    assert result.schedules == () and result.discard_reasons["unknown"] == 1
    existing_conflict = generate_schedules(
        GenerationRequest(required_disciplines=("A",), existing_bundles=(valid, valid)),
        {"A": [valid]},
    )
    assert existing_conflict.discard_reasons["conflict"] == 1
    incomplete_meeting = Bundle(
        id="bundle:A:incomplete-meeting",
        discipline_code="A",
        section_ids=(),
        meetings=(Meeting("mon", None, None, None, None, "", ""),),
        professors=(),
        selectable=True,
        schedule_status="complete",
    )
    metrics = generate_schedules(
        GenerationRequest(
            required_disciplines=("A",),
            preferences=Preferences(preferred_windows=(("mon", 600, 700),)),
        ),
        {"A": [incomplete_meeting]},
    )
    assert metrics.schedules


@given(st.lists(st.integers(0, 5), min_size=2, max_size=3, unique=True))
@settings(max_examples=20)
def test_generator_matches_brute_force_for_small_inputs(starts: list[int]) -> None:
    candidates = {
        "A": [
            bundle("A", str(i), "mon", start * 60, start * 60 + 30)
            for i, start in enumerate(starts)
        ],
        "B": [
            bundle("B", str(i), "mon", start * 60 + 30, start * 60 + 60)
            for i, start in enumerate(starts)
        ],
    }
    result = generate_schedules(
        GenerationRequest(
            required_disciplines=("A", "B"),
            max_results=50,
            preferences=Preferences(days_weight=0, gaps_weight=0),
        ),
        candidates,
    )
    brute_force = sorted(
        tuple(sorted((left.id, right.id)))
        for left, right in product(candidates["A"], candidates["B"])
    )
    assert [item.bundle_ids for item in result.schedules] == brute_force
