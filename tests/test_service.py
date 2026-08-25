from pathlib import Path

import pytest

from matrusp_mcp.api_models import (
    CheckConflictsInput,
    CompareSchedulesInput,
    FindGapFillersInput,
    GenerateSchedulesInput,
    GetCurriculumInput,
    GetDisciplineInput,
    SearchCurriculaInput,
    SearchOfferingsInput,
)
from matrusp_mcp.service import PublicError, Service
from matrusp_mcp.snapshot import build_snapshot

from .test_snapshot_repository import sample_data


@pytest.fixture
def service(tmp_path: Path) -> Service:
    snapshot = tmp_path / "snapshot.sqlite"
    build_snapshot(sample_data(), snapshot)
    return Service.from_path(snapshot)


def test_all_eight_service_operations_return_provenance(service: Service) -> None:
    calls = [
        service.search_offerings(SearchOfferingsInput(query="MAC0001")),
        service.get_discipline(GetDisciplineInput(code="MAC0001")),
        service.find_gap_fillers(
            FindGapFillersInput(day="mon", start_time="09:00", end_time="13:00")
        ),
        service.check_schedule_conflicts(CheckConflictsInput(bundle_ids=["bundle:MAC0001:20262A"])),
        service.generate_schedules(GenerateSchedulesInput(required_disciplines=["MAC0001"])),
        service.compare_schedules(CompareSchedulesInput(alternatives=[["bundle:MAC0001:20262A"]])),
        service.search_curricula(SearchCurriculaInput(query="computacao")),
    ]
    for response in calls:
        assert response.snapshot_id == "test-snapshot"
        assert response.observed_at == "2026-08-25T00:00:00Z"
    with pytest.raises(PublicError) as error:
        service.get_curriculum(GetCurriculumInput(curriculum_id="curriculum:missing:missing"))
    assert error.value.code == "not_found"


def test_invalid_input_and_unknown_schedule_never_claim_no_conflict(service: Service) -> None:
    with pytest.raises(PublicError) as error:
        service.find_gap_fillers(
            FindGapFillersInput(day="mon", start_time="13:00", end_time="12:00")
        )
    assert error.value.code == "invalid_input"
    response = service.check_schedule_conflicts(
        CheckConflictsInput(section_ids=["section:MAC0002:20262B"])
    )
    assert response.data["state"] == "unknown"


def test_service_filters_conflicts_generates_and_compares(service: Service) -> None:
    assert service.search_offerings(
        SearchOfferingsInput(start_time="09:00", end_time="13:00")
    ).data["items"]
    assert (
        service.find_gap_fillers(
            FindGapFillersInput(
                day="mon",
                start_time="09:00",
                end_time="13:00",
                bundle_ids=["bundle:MAC0001:20262A"],
            )
        ).data["items"]
        == []
    )
    conflicts = service.check_schedule_conflicts(
        CheckConflictsInput(bundle_ids=["bundle:MAC0001:20262A", "bundle:MAC0001:20262A"])
    )
    assert conflicts.data["state"] == "conflict"
    schedules = service.generate_schedules(
        GenerateSchedulesInput(
            required_disciplines=["MAC0001"], allowed_bundle_ids=["bundle:MAC0001:20262A"]
        )
    )
    assert schedules.data["schedules"]
    compared = service.compare_schedules(
        CompareSchedulesInput(alternatives=[["bundle:MAC0001:20262A"], []])
    )
    assert len(compared.data["alternatives"]) == 2


def test_service_curriculum_and_cursor_errors(service: Service) -> None:
    assert service.search_curricula(
        SearchCurriculaInput(query="computacao", unit_code="45", campus="sao paulo")
    ).data["items"]
    assert service.get_curriculum(
        GetCurriculumInput(curriculum_id="curriculum:CC:bacharelado")
    ).data["items"]
    with pytest.raises(PublicError) as error:
        service.search_offerings(SearchOfferingsInput(cursor="bad"))
    assert error.value.code == "stale_cursor"
    with pytest.raises(PublicError) as error:
        service.compare_schedules(CompareSchedulesInput(alternatives=[["missing"]]))
    assert error.value.code == "not_found"
    with pytest.raises(PublicError) as error:
        service.find_gap_fillers(
            FindGapFillersInput(
                day="mon", start_time="09:00", end_time="13:00", bundle_ids=["missing"]
        )
    )
    assert error.value.code == "not_found"


def test_manual_blocks_are_applied_to_conflicts_and_generation(service: Service) -> None:
    block = {"day": "MON", "start_time": "09:00", "end_time": "11:00"}
    conflicts = service.check_schedule_conflicts(
        CheckConflictsInput(bundle_ids=["bundle:MAC0001:20262A"], blocks=[block])
    )
    assert conflicts.data["state"] == "conflict"
    schedules = service.generate_schedules(
        GenerateSchedulesInput(required_disciplines=["MAC0001"], blocks=[block])
    )
    assert schedules.data["schedules"] == []
    compared = service.compare_schedules(
        CompareSchedulesInput(
            alternatives=[["bundle:MAC0001:20262A"]], blocks=[block]
        )
    )
    assert compared.data["alternatives"][0]["state"] == "conflict"


def test_contained_gap_and_preference_window_validation(service: Service) -> None:
    contained = service.find_gap_fillers(
        FindGapFillersInput(
            day="segunda-feira",
            start_time="09:00",
            end_time="11:00",
            window_mode="contained",
        )
    )
    assert contained.data["items"] == []
    with pytest.raises(PublicError) as error:
        service.generate_schedules(
            GenerateSchedulesInput(
                required_disciplines=["MAC0001"],
                preferences={"preferred_windows": [{"day": "mon", "start_time": "bad"}]},
            )
        )
    assert error.value.code == "invalid_input"
    generated = service.generate_schedules(
        GenerateSchedulesInput(
            required_disciplines=["MAC0001"],
            preferences={
                "preferred_windows": [{"day": "segunda", "start_time": "09:00", "end_time": "13:00"}]
            },
        )
    )
    assert generated.data["schedules"]


def test_discriminated_conflict_items_and_compare_ranking(service: Service) -> None:
    result = service.check_schedule_conflicts(
        CheckConflictsInput(
            items=[
                {"bundle_id": "bundle:MAC0001:20262A"},
                {"section_id": "section:MAC0001:20262A"},
                {"block": {"day": "tue", "start_time": "08:00", "end_time": "09:00"}},
            ]
        )
    )
    assert result.data["state"] == "conflict"
    assert result.data["conflicts"][0]["meetings"]
    compared = service.compare_schedules(
        CompareSchedulesInput(
            alternatives=[[], ["bundle:MAC0001:20262A"]],
            preferences={"preferred_professors": ["Ada"]},
        )
    )
    assert all("score" in item and "metrics" in item for item in compared.data["alternatives"])


def test_generation_hard_constraints_and_invalid_sections(service: Service) -> None:
    generated = service.generate_schedules(
        GenerateSchedulesInput(
            required_disciplines=["MAC0001"],
            hard_constraints={"required_days": ["segunda"]},
        )
    )
    assert generated.data["schedules"]
    with pytest.raises(PublicError) as error:
        service.generate_schedules(
            GenerateSchedulesInput(
                required_disciplines=["MAC0001"], allowed_bundle_ids=["missing"]
            )
        )
    assert error.value.code == "not_found"
    with pytest.raises(PublicError) as error:
        service.check_schedule_conflicts(
            CheckConflictsInput(
                blocks=[
                    {
                        "day": "mon",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "start_date": "bad",
                    }
                ]
            )
        )
    assert error.value.code == "invalid_input"
    with pytest.raises(PublicError) as error:
        service.check_schedule_conflicts(
            CheckConflictsInput(items=[{"section_id": "section:missing"}])
        )
    assert error.value.code == "not_found"
