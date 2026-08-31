"""Estruturas intermediárias do crawler."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import CurriculumItem, Section, Vacancy


@dataclass(frozen=True, slots=True)
class UnitCandidate:
    code: str
    name: str
    source_campus_name: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateDiscipline:
    code: str
    name: str
    verdis: str | None
    unit_codes: tuple[str, ...]
    verdis_seen: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateCurriculum:
    """Link discovered in the current (``tipo=N``) curriculum index."""

    course_code: str
    habilitation_code: str
    name: str
    unit_code: str | None
    detail_url: str | None = None
    campus: str | None = None
    period_code: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedCurriculum:
    candidate: CandidateCurriculum
    items: tuple[CurriculumItem, ...]
    source_campus_name: str | None = None
    source_period_code: str | None = None
    status: str = "confirmed"
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedSections:
    status: str
    sections: tuple[Section, ...] = ()
    vacancies: dict[str, tuple[Vacancy, ...]] = field(
        default_factory=dict[str, tuple[Vacancy, ...]]
    )
    message: str | None = None
