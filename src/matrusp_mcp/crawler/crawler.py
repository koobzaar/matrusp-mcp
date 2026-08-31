"""Crawler assíncrono do JupiterWeb com política de publicação segura."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import random
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import httpx

from ..bundles import derive_bundles
from ..campus import CampusOverride, apply_campus_override, normalize_campus
from ..domain import Curriculum, CurriculumItem, Discipline, OfferingHistory, Unit, Vacancy
from ..snapshot import SnapshotData, SnapshotMetadata
from .models import CandidateCurriculum, CandidateDiscipline, ParsedCurriculum, ParsedSections
from .parsers import (
    deduplicate_candidates,
    parse_curriculum_detail,
    parse_curriculum_index,
    parse_discipline_detail,
    parse_discipline_index,
    parse_sections_page,
    parse_units,
)

BASE_URL = "https://uspdigital.usp.br/jupiterweb/"
Fetcher = Callable[[str, bool, float], Awaitable[tuple[int, bytes]]]
Sleeper = Callable[[float], Awaitable[None] | None]


class CrawlError(RuntimeError):
    """Falha que deve abortar o release, preservando o snapshot anterior."""


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    timeout_seconds: float = 60
    attempts: int = 4
    concurrency: int = 8
    user_agent: str = "MatrUSP-MCP/0.1 (+https://github.com/matrusp/matrusp-mcp)"

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ValueError("timeout_seconds must be between 0 and 60")
        if self.attempts != 4:
            raise ValueError("the release policy requires four attempts")
        if not 1 <= self.concurrency <= 16:
            raise ValueError("concurrency must be between 1 and 16")


@dataclass(frozen=True, slots=True)
class CandidateState:
    code: str
    state: str
    reason: str | None = None


class JupiterCrawler:
    def __init__(
        self,
        policy: FetchPolicy | None = None,
        *,
        fetcher: Fetcher | None = None,
        sleep: Sleeper | None = None,
        previous_versions: dict[tuple[str, str], dict[str, Any]] | None = None,
        previous_history: dict[tuple[str, str], OfferingHistory] | None = None,
        campus_overrides: dict[str, CampusOverride] | None = None,
        collect_curricula: bool = True,
        observed_at: datetime | None = None,
    ) -> None:
        self.policy = policy or FetchPolicy()
        self.fetcher = fetcher or self._default_fetch
        self.sleep = sleep or asyncio.sleep
        self.previous_versions = previous_versions or {}
        self.previous_history = previous_history or {}
        self.campus_overrides = campus_overrides or {}
        self.collect_curricula = collect_curricula
        self.observed_at = (observed_at or datetime.now(UTC)).astimezone(UTC)
        self.states: list[CandidateState] = []
        self.source_checksums: dict[str, str] = {}
        self._semaphore = asyncio.Semaphore(self.policy.concurrency)

    async def _default_fetch(self, url: str, verify: bool, timeout: float) -> tuple[int, bytes]:
        del (
            verify
        )  # httpx always verifies TLS unless explicitly configured otherwise; we never disable it.
        async with httpx.AsyncClient(
            timeout=timeout, verify=True, headers={"User-Agent": self.policy.user_agent}
        ) as client:
            response = await client.get(url)
            return response.status_code, response.content

    async def _fetch_with_retry(self, url: str) -> tuple[int, bytes]:
        last_error: Exception | None = None
        deadline = asyncio.get_running_loop().time() + self.policy.timeout_seconds
        for attempt in range(self.policy.attempts):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            attempts_left = self.policy.attempts - attempt
            attempt_timeout = min(self.policy.timeout_seconds, remaining / attempts_left)
            try:
                async with self._semaphore:
                    status, body = await self.fetcher(
                        url, True, attempt_timeout
                    )
                if status == 200:
                    self.source_checksums[url] = hashlib.sha256(body).hexdigest()
                    return status, body
                last_error = CrawlError(f"fetch_error: HTTP {status} for {url}")
            except (
                Exception
            ) as error:  # network libraries expose several transient exception classes
                last_error = error
            if attempt + 1 < self.policy.attempts:
                delay = (2**attempt) * 0.25 + random.Random(f"{url}:{attempt}").uniform(0, 0.1)
                if asyncio.get_running_loop().time() + delay >= deadline:
                    break
                maybe_awaitable = self.sleep(delay)
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
        raise CrawlError(f"fetch_error: {url}") from last_error

    def should_fetch_discipline(self, candidate: CandidateDiscipline) -> bool:
        return (
            candidate.verdis is None
            or (candidate.code, candidate.verdis) not in self.previous_versions
        )

    async def _fetch_candidate(
        self, candidate: CandidateDiscipline
    ) -> tuple[CandidateDiscipline, ParsedSections]:
        try:
            _, body = await self._fetch_with_retry(
                f"{BASE_URL}obterTurma?print=true&sgldis={candidate.code}"
            )
        except CrawlError as error:
            self.states.append(CandidateState(candidate.code, "fetch_error", str(error)))
            raise
        parsed = parse_sections_page(
            body, candidate.code, self.observed_at.isoformat().replace("+00:00", "Z")
        )
        if parsed.status == "invalid_source":
            self.states.append(CandidateState(candidate.code, "parse_error", parsed.message))
            raise CrawlError(f"parse_error: {candidate.code}")
        self.states.append(CandidateState(candidate.code, parsed.status))
        return candidate, parsed

    async def _fetch_curriculum(
        self, candidate: CandidateCurriculum
    ) -> ParsedCurriculum:
        url = candidate.detail_url or (
            f"{BASE_URL}jupCurso?codcur={candidate.course_code}"
            f"&codhab={candidate.habilitation_code}&tipo=N"
        )
        try:
            _, body = await self._fetch_with_retry(url)
        except CrawlError as error:
            self.states.append(
                CandidateState(
                    f"{candidate.course_code}:{candidate.habilitation_code}",
                    "fetch_error",
                    str(error),
                )
            )
            raise
        parsed = parse_curriculum_detail(body, candidate)
        valid_status = (
            (parsed.status == "confirmed" and bool(parsed.items))
            or (parsed.status == "no_current_curriculum" and not parsed.items)
        )
        if not valid_status:
            self.states.append(
                CandidateState(
                    f"{candidate.course_code}:{candidate.habilitation_code}",
                    "parse_error",
                    parsed.message or "inconsistent curriculum parser result",
                )
            )
            raise CrawlError(
                f"parse_error: curriculum {candidate.course_code}:{candidate.habilitation_code}"
            )
        self.states.append(
            CandidateState(
                f"{candidate.course_code}:{candidate.habilitation_code}", parsed.status
            )
        )
        return parsed

    async def _fetch_discipline_detail(self, candidate: CandidateDiscipline) -> tuple[str, bytes]:
        _, detail = await self._fetch_with_retry(
            f"{BASE_URL}obterDisciplina?print=true&sgldis={candidate.code}"
        )
        return candidate.code, detail

    @staticmethod
    def _discipline_from_candidate(
        candidate: CandidateDiscipline, unit_code: str | None, detail: bytes | None
    ) -> Discipline:
        if detail is not None:
            return parse_discipline_detail(detail, candidate, unit_code)
        return Discipline(
            candidate.code,
            candidate.name,
            unit_code,
            None,
            candidate.verdis,
            0,
            0,
            is_stub=True,
            unit_codes=candidate.unit_codes,
            versions=candidate.verdis_seen
            or ((candidate.verdis,) if candidate.verdis else ()),
        )

    async def crawl(self) -> SnapshotData:
        started = datetime.now(UTC)
        _, units_body = await self._fetch_with_retry(f"{BASE_URL}jupColegiadoLista?tipo=T")
        unit_candidates = parse_units(units_body)
        if not unit_candidates:
            raise CrawlError("invalid_source: no units")

        async def index(unit: Any) -> tuple[Any, ...]:
            _, body = await self._fetch_with_retry(
                f"{BASE_URL}jupDisciplinaLista?letra=A-Z&tipo=T&codcg={unit.code}"
            )
            return parse_discipline_index(body, unit)

        indexed = await asyncio.gather(*(index(unit) for unit in unit_candidates))
        candidates = deduplicate_candidates([candidate for group in indexed for candidate in group])
        if not candidates:
            raise CrawlError("invalid_source: no discipline candidates")
        parsed_results = await asyncio.gather(
            *(self._fetch_candidate(candidate) for candidate in candidates)
        )
        curriculum_candidates: tuple[CandidateCurriculum, ...] = ()
        if self.collect_curricula:
            async def curriculum_index(unit: Any) -> tuple[CandidateCurriculum, ...]:
                _, body = await self._fetch_with_retry(
                    f"{BASE_URL}jupCursoLista?tipo=N&codcg={unit.code}"
                )
                return parse_curriculum_index(body, unit, base_url=BASE_URL)

            curriculum_indexed = await asyncio.gather(
                *(curriculum_index(unit) for unit in unit_candidates)
            )
            curriculum_by_key: dict[tuple[str, str, str | None], CandidateCurriculum] = {}
            for group in curriculum_indexed:
                for candidate in group:
                    curriculum_by_key[
                        (candidate.course_code, candidate.habilitation_code, candidate.unit_code)
                    ] = candidate
            curriculum_candidates = tuple(
                sorted(
                    curriculum_by_key.values(),
                    key=lambda item: (item.course_code, item.habilitation_code, item.unit_code or ""),
                )
            )
            if not curriculum_candidates:
                raise CrawlError("invalid_source: no curriculum candidates")
        parsed_curricula = (
            await asyncio.gather(*(self._fetch_curriculum(item) for item in curriculum_candidates))
            if curriculum_candidates
            else ()
        )
        discipline_details = dict(
            await asyncio.gather(
                *(
                    self._fetch_discipline_detail(candidate)
                    for candidate, _ in parsed_results
                    if self.should_fetch_discipline(candidate)
                )
            )
        )
        disciplines: list[Discipline] = []
        sections = []
        vacancies: list[Vacancy] = []
        for candidate, parsed in parsed_results:
            unit_code = candidate.unit_codes[0] if candidate.unit_codes else None
            detail = discipline_details.get(candidate.code)
            cached = (
                self.previous_versions.get((candidate.code, candidate.verdis or ""))
                if detail is None
                else None
            )
            if cached is not None:
                disciplines.append(
                    Discipline(
                        candidate.code,
                        str(cached.get("name", candidate.name)),
                        unit_code,
                        cast(str | None, cached.get("department")),
                        candidate.verdis,
                        int(cached.get("aula_credits", 0)),
                        int(cached.get("work_credits", 0)),
                        cast(str | None, cached.get("objectives")),
                        cast(str | None, cached.get("summary")),
                        bool(cached.get("is_stub", False)),
                        candidate.unit_codes,
                        candidate.verdis_seen or ((candidate.verdis,) if candidate.verdis else ()),
                    )
                )
            else:
                disciplines.append(self._discipline_from_candidate(candidate, unit_code, detail))
            sections.extend(parsed.sections)
            vacancies.extend(item for values in parsed.vacancies.values() for item in values)
        curricula: list[Curriculum] = []
        for parsed_curriculum in parsed_curricula:
            curriculum_id = (
                f"curriculum:{parsed_curriculum.candidate.course_code}:"
                f"{parsed_curriculum.candidate.habilitation_code}"
            )
            items = tuple(
                item if item.curriculum_id == curriculum_id else CurriculumItem(
                    curriculum_id,
                    item.ideal_period,
                    item.discipline_code,
                    item.item_type,
                    item.weak_prerequisites,
                    item.strong_prerequisites,
                    item.set_indications,
                    item.name,
                    item.aula_credits,
                    item.work_credits,
                )
                for item in parsed_curriculum.items
            )
            curricula.append(
                Curriculum(
                    curriculum_id,
                    parsed_curriculum.candidate.course_code,
                    parsed_curriculum.candidate.habilitation_code,
                    parsed_curriculum.candidate.name,
                    parsed_curriculum.candidate.unit_code,
                    normalize_campus(parsed_curriculum.candidate.campus),
                    parsed_curriculum.candidate.period_code,
                    items,
                )
            )
            existing_codes = {discipline.code for discipline in disciplines}
            for item in items:
                if item.discipline_code in existing_codes:
                    continue
                disciplines.append(
                    Discipline(
                        item.discipline_code,
                        item.name or item.discipline_code,
                        parsed_curriculum.candidate.unit_code,
                        None,
                        None,
                        item.aula_credits or 0,
                        item.work_credits or 0,
                        is_stub=True,
                    )
                )
                existing_codes.add(item.discipline_code)
        # Keep removed disciplines as stubs so offering_history remains queryable
        # without pretending that the discipline is currently offered.
        current_codes = {discipline.code for discipline in disciplines}
        historical_codes = {
            code for code, _period in self.previous_history if code not in current_codes
        }
        for code in sorted(historical_codes):
            version_values = [
                (version, value)
                for (cached_code, version), value in self.previous_versions.items()
                if cached_code == code
            ]
            if not version_values:
                disciplines.append(Discipline(code, code, None, None, None, 0, 0, is_stub=True))
                continue
            version, cached = max(version_values, key=lambda item: item[0])
            disciplines.append(
                Discipline(
                    code,
                    str(cached.get("name", code)),
                    None,
                    cast(str | None, cached.get("department")),
                    version,
                    int(cached.get("aula_credits", 0)),
                    int(cached.get("work_credits", 0)),
                    cast(str | None, cached.get("objectives")),
                    cast(str | None, cached.get("summary")),
                    True,
                )
            )
        observed = self.observed_at
        metadata = SnapshotMetadata(
            snapshot_id=observed.strftime("%Y%m%dT%H%M%SZ"),
            schema_version=1,
            crawl_started_at=started,
            crawl_finished_at=datetime.now(UTC),
            observed_at=observed,
            crawler_commit=os.environ.get("GITHUB_SHA", os.environ.get("MATRUSP_CRAWLER_COMMIT", "unknown")),
            source_urls=(
                f"{BASE_URL}jupColegiadoLista?tipo=T",
                f"{BASE_URL}jupDisciplinaLista?tipo=T",
                f"{BASE_URL}jupCursoLista?tipo=N",
            ),
            checksums=dict(sorted(self.source_checksums.items())),
            state_counts=dict(sorted(Counter(item.state for item in self.states).items())),
        )
        curriculum_campuses: dict[str, str] = {}
        for parsed_curriculum in parsed_curricula:
            unit_code = parsed_curriculum.candidate.unit_code
            source_campus = parsed_curriculum.source_campus_name
            if unit_code and source_campus and unit_code not in curriculum_campuses:
                curriculum_campuses[unit_code] = source_campus
        units = tuple(
            apply_campus_override(
                Unit(
                    unit.code,
                    unit.name,
                    normalize_campus(curriculum_campuses.get(unit.code) or unit.source_campus_name),
                    curriculum_campuses.get(unit.code) or unit.source_campus_name,
                    None,
                ),
                self.campus_overrides.get(unit.code),
            )
            for unit in unit_candidates
        )
        sections_tuple = tuple(sections)
        current_history = {
            (discipline.code, period): OfferingHistory(
                discipline.code,
                period,
                observed.isoformat().replace("+00:00", "Z"),
                observed.isoformat().replace("+00:00", "Z"),
                sum(
                    section.discipline_code == discipline.code and section.period_code == period
                    for section in sections_tuple
                ),
            )
            for discipline in disciplines
            for period in sorted(
                {
                    section.period_code
                    for section in sections_tuple
                    if section.discipline_code == discipline.code
                }
            )
        }
        merged_history: dict[tuple[str, str], OfferingHistory] = dict(self.previous_history)
        for key, value in current_history.items():
            previous = merged_history.get(key)
            merged_history[key] = (
                value
                if previous is None
                else OfferingHistory(
                    value.discipline_code,
                    value.period_code,
                    min(previous.first_observed_at, value.first_observed_at),
                    max(previous.last_observed_at, value.last_observed_at),
                    max(previous.max_sections, value.max_sections),
                )
            )
        history = tuple(
            merged_history[key]
            for key in sorted(merged_history)
        )
        return SnapshotData(
            metadata,
            units,
            tuple(disciplines),
            sections_tuple,
            derive_bundles(sections_tuple),
            tuple(curricula),
            tuple(vacancies),
            history,
        )
