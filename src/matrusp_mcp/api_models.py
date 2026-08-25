"""Contratos Pydantic públicos das oito operações MCP."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchOfferingsInput(StrictModel):
    query: str | None = None
    professor: str | None = None
    campus: str | None = None
    unit_code: str | None = None
    department: str | None = None
    days: list[str] = Field(default_factory=list)
    start_time: str | None = None
    end_time: str | None = None
    window_mode: Literal["overlaps", "contained"] = "overlaps"
    include_unknown: bool = False
    limit: int = Field(default=20, ge=1, le=50)
    cursor: str | None = None


class GetDisciplineInput(StrictModel):
    code: str


class FindGapFillersInput(StrictModel):
    day: str
    start_time: str
    end_time: str
    window_mode: Literal["overlaps", "contained"] = "overlaps"
    bundle_ids: list[str] = Field(default_factory=list)
    section_ids: list[str] = Field(default_factory=list)
    include_unknown: bool = False


class CheckConflictsInput(StrictModel):
    bundle_ids: list[str] = Field(default_factory=list)
    section_ids: list[str] = Field(default_factory=list)
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Discriminated items: {bundle_id}, {section_id}, or a manual block.",
    )


class PreferencesInput(StrictModel):
    days_weight: int = Field(default=1, ge=0, le=100)
    gaps_weight: int = Field(default=1, ge=0, le=100)
    outside_preferred_windows_weight: int = Field(default=0, ge=0, le=100)
    avoided_professors_weight: int = Field(default=0, ge=0, le=100)
    preferred_professors_weight: int = Field(default=0, ge=0, le=100)
    avoided_professors: list[str] = Field(default_factory=list)
    preferred_professors: list[str] = Field(default_factory=list)
    preferred_windows: list[dict[str, Any]] = Field(default_factory=list)


class GenerateSchedulesInput(StrictModel):
    required_disciplines: list[str] = Field(min_length=1, max_length=15)
    allowed_bundle_ids: list[str] = Field(default_factory=list)
    existing_bundle_ids: list[str] = Field(default_factory=list)
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    max_results: int = Field(default=10, ge=1, le=50)
    node_budget: int = Field(default=1_000_000, ge=1, le=1_000_000)
    preferences: PreferencesInput = PreferencesInput()
    hard_constraints: dict[str, Any] = Field(default_factory=dict)


class CompareSchedulesInput(StrictModel):
    alternatives: list[list[str]] = Field(min_length=1, max_length=50)
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    preferences: PreferencesInput = PreferencesInput()


class SearchCurriculaInput(StrictModel):
    query: str | None = None
    unit_code: str | None = None
    campus: str | None = None
    limit: int = Field(default=20, ge=1, le=50)


class GetCurriculumInput(StrictModel):
    curriculum_id: str


class PublicResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str
    observed_at: str
    warnings: list[str] = Field(default_factory=list)
    data: dict[str, Any]
