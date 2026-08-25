"""Tipos de domínio independentes de HTML, SQLite e MCP."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from .normalize import normalize_text


class ConflictState(StrEnum):
    CONFLICT = "conflict"
    NO_CONFLICT = "no_conflict"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Professor:
    display_name: str
    normalized_name: str
    responsible: bool = False

    @classmethod
    def from_source(cls, value: str) -> Professor:
        stripped = " ".join(value.split())
        responsible = stripped.startswith("(R)")
        if responsible:
            stripped = stripped[3:].strip()
        return cls(stripped, normalize_text(stripped), responsible)


@dataclass(frozen=True, slots=True)
class Meeting:
    day: str
    start_minute: int | None
    end_minute: int | None
    start_date: date | None
    end_date: date | None
    start_text: str
    end_text: str
    original_day: str = ""


@dataclass(frozen=True, slots=True)
class Unit:
    code: str
    name: str
    campus: str | None
    source_campus_name: str | None
    provenance: str | None


@dataclass(frozen=True, slots=True)
class Discipline:
    code: str
    name: str
    unit_code: str | None
    department: str | None
    version: str | None
    aula_credits: int
    work_credits: int
    objectives: str | None = None
    summary: str | None = None
    is_stub: bool = False
    unit_codes: tuple[str, ...] = ()
    versions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Section:
    id: str
    discipline_code: str
    section_code: str
    period_code: str
    start_date: date | None
    end_date: date | None
    section_type: str
    notes: str
    schedule_status: str
    meetings: tuple[Meeting, ...] = ()
    professors: tuple[Professor, ...] = ()
    linked_theory_section_code: str | None = None
    data_quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Bundle:
    id: str
    discipline_code: str
    section_ids: tuple[str, ...]
    meetings: tuple[Meeting, ...]
    professors: tuple[Professor, ...]
    selectable: bool
    schedule_status: str
    data_quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Vacancy:
    section_id: str
    category: str
    group_name: str | None
    available_text: str | None
    registered_text: str | None
    pending_text: str | None
    enrolled_text: str | None
    observed_at: str


@dataclass(frozen=True, slots=True)
class OfferingHistory:
    discipline_code: str
    period_code: str
    first_observed_at: str
    last_observed_at: str
    max_sections: int


@dataclass(frozen=True, slots=True)
class CurriculumItem:
    curriculum_id: str
    ideal_period: str
    discipline_code: str
    item_type: str
    weak_prerequisites: tuple[str, ...] = ()
    strong_prerequisites: tuple[str, ...] = ()
    set_indications: tuple[str, ...] = ()
    name: str | None = None
    aula_credits: int | None = None
    work_credits: int | None = None


@dataclass(frozen=True, slots=True)
class Curriculum:
    id: str
    course_code: str
    habilitation_code: str
    name: str
    unit_code: str | None
    campus: str | None
    period_code: str | None
    items: tuple[CurriculumItem, ...] = ()


@dataclass(frozen=True, slots=True)
class Block:
    """Bloqueio manual, usado pela mesma semântica dos encontros."""

    id: str
    meeting: Meeting


@dataclass(frozen=True, slots=True)
class ScheduleMetrics:
    active_days: int
    total_gap_hours: float
    hours_outside_preferred_windows: float
    avoided_professor_matches: int
    preferred_professor_matches: int


@dataclass(frozen=True, slots=True)
class RankedSchedule:
    bundle_ids: tuple[str, ...]
    score: float
    metrics: ScheduleMetrics


@dataclass(frozen=True, slots=True)
class GenerationResult:
    schedules: tuple[RankedSchedule, ...]
    truncated: bool
    explored_nodes: int
    discard_reasons: dict[str, int] = field(default_factory=dict[str, int])
