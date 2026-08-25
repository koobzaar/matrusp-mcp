"""Parsers semânticos e tolerantes para as páginas HTML do JupiterWeb."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from ..domain import CurriculumItem, Discipline, Meeting, Professor, Section, Vacancy
from ..normalize import normalize_day, normalize_text, parse_time
from .models import (
    CandidateCurriculum,
    CandidateDiscipline,
    ParsedCurriculum,
    ParsedSections,
    UnitCandidate,
)

_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,31}$")
_CURRICULUM_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,31}$")
_NO_OFFER = re.compile(
    r"(?:n(?:a|\?)o\s+(?:existem|ha)\s+(?:turmas?|ofertas?)|"
    r"n(?:a|\?)o\s+existe\s+oferecimento|sem\s+(?:turmas?|ofertas?)|"
    r"nenhum(?:a)?\s+(?:turma|oferta)|n(?:a|\?)o\s+foram\s+encontrad[ao]s?\s+turmas?|"
    r"n(?:a|\?)o\s+ha\s+oferta|oferta\s+inexistente)",
    re.I,
)


def _soup(document: str | bytes) -> BeautifulSoup:
    return BeautifulSoup(document, "html5lib")


def _text(node: Tag) -> str:
    return " ".join(node.stripped_strings).strip()


def _cells(row: Tag) -> list[str]:
    return [_text(cell) for cell in row.find_all(["th", "td"], recursive=False)]


def _owned_rows(table: Tag) -> list[Tag]:
    """Return only rows whose nearest table ancestor is ``table``."""
    return [row for row in table.find_all("tr") if row.find_parent("table") is table]


def _expanded_cells(row: Tag) -> list[str]:
    """Expand colspans so source columns remain aligned across differently shaped rows."""
    result: list[str] = []
    for cell in row.find_all(["th", "td"], recursive=False):
        value = _text(cell)
        try:
            colspan = max(1, int(str(cell.get("colspan", "1"))))
        except ValueError:
            colspan = 1
        result.append(value)
        result.extend("" for _ in range(colspan - 1))
    return result


def _query(href: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(href).query, keep_blank_values=True)


def parse_units(document: str | bytes) -> tuple[UnitCandidate, ...]:
    soup = _soup(document)
    result: list[UnitCandidate] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = str(link.get("href", ""))
        if "jupColegiadoMenu" not in href:
            continue
        params = _query(href)
        code = (params.get("codcg") or [""])[0].strip()
        name = _text(link)
        source_campus = (
            str(link.get("data-campus", "")).strip()
            or (params.get("campus") or [""])[0].strip()
            or None
        )
        if not code or not name or code in seen:
            continue
        seen.add(code)
        result.append(UnitCandidate(code, name, source_campus))
    return tuple(sorted(result, key=lambda item: item.code))


def parse_discipline_index(
    document: str | bytes, unit: UnitCandidate
) -> tuple[CandidateDiscipline, ...]:
    soup = _soup(document)
    result: list[CandidateDiscipline] = []
    for link in soup.find_all("a", href=True):
        href = str(link.get("href", ""))
        if "obterTurma" not in href and "obterDisciplina" not in href:
            continue
        params = _query(href)
        code = (
            params.get("sgldis")
            or params.get("coddis")
            or params.get("coddisciplina")
            or [""]
        )[0].strip().replace(" ", "")
        if not _CODE.fullmatch(code):
            continue
        verdis = (params.get("verdis") or [None])[0]
        result.append(CandidateDiscipline(code, _text(link) or code, verdis, (unit.code,)))
    return tuple(result)


def deduplicate_candidates(
    candidates: list[CandidateDiscipline] | tuple[CandidateDiscipline, ...],
) -> tuple[CandidateDiscipline, ...]:
    grouped: dict[str, list[CandidateDiscipline]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.code, []).append(candidate)
    result: list[CandidateDiscipline] = []
    for code in sorted(grouped):
        values = grouped[code]
        names = sorted(
            (item.name for item in values), key=lambda item: (normalize_text(item), item)
        )
        units = tuple(sorted({unit for item in values for unit in item.unit_codes}))
        versions = tuple(
            sorted(
                {
                    version
                    for item in values
                    for version in (item.verdis_seen or ((item.verdis,) if item.verdis else ()))
                    if version is not None
                }
            )
        )
        latest = versions[-1] if versions else None
        result.append(CandidateDiscipline(code, names[0], latest, units, versions))
    return tuple(result)


def _first_parameter(params: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        value = (params.get(name) or [""])[0].strip()
        if value:
            return value
    return None


def _curriculum_candidate_from_link(
    link: Tag,
    unit_code: str | None,
    *,
    base_url: str = "https://uspdigital.usp.br/jupiterweb/",
    campus: str | None = None,
) -> CandidateCurriculum | None:
    href = str(link.get("href", ""))
    params = _query(href)
    if (params.get("tipo") or [""])[0].upper() == "V":
        return None
    if not href and link.name == "option":
        raw_value = str(link.get("value", "")).strip()
        # Older pages encode the pair as ``course;habilitation`` or ``course:habilitation``.
        parts = re.split(r"[;|:]", raw_value, maxsplit=1)
        if parts and parts[0]:
            params["codcur"] = [parts[0]]
            if len(parts) == 2 and parts[1]:
                params["codhab"] = [parts[1]]
    course_code = _first_parameter(
        params, "codcur", "codcurso", "codcursof", "sglcur", "curso"
    )
    habilitation = _first_parameter(
        params, "codhab", "codhabilitacao", "codhabil", "habilitacao", "habil", "habilit"
    )
    is_curriculum_link = any(
        marker in href.casefold() for marker in ("jupcurso", "obtercurso", "curricul")
    )
    if course_code is None and is_curriculum_link:
        data_code = str(link.get("data-codcur", "")).strip()
        course_code = data_code or None
    if course_code is None or not _CURRICULUM_CODE.fullmatch(course_code):
        return None
    if not is_curriculum_link and not any(
        key in params for key in ("codhab", "codhabilitacao", "habilitacao", "habil")
    ):
        return None
    habilitation = habilitation or "default"
    if not _CODE.fullmatch(habilitation):
        habilitation = normalize_text(habilitation).replace(" ", "-") or "default"
    text = _text(link) or course_code
    return CandidateCurriculum(
        course_code=course_code,
        habilitation_code=habilitation,
        name=text,
        unit_code=unit_code,
        detail_url=urljoin(base_url, href) if href else None,
        campus=campus,
        period_code=_first_parameter(params, "periodo", "period", "anocurriculo"),
    )


def parse_curriculum_index(
    document: str | bytes,
    unit: UnitCandidate | None = None,
    *,
    base_url: str = "https://uspdigital.usp.br/jupiterweb/",
) -> tuple[CandidateCurriculum, ...]:
    """Parse the current curriculum index (never the historical ``tipo=V`` index)."""
    soup = _soup(document)
    campus = next(
        (
            match.group(1).strip()
            for value in soup.stripped_strings
            if (match := re.match(r"\s*Campus\s*:\s*(.+)", value, re.I)) is not None
        ),
        unit.source_campus_name if unit is not None else None,
    )
    values: dict[tuple[str, str, str | None], CandidateCurriculum] = {}
    for link in soup.find_all(["a", "option"]):
        candidate = _curriculum_candidate_from_link(
            link,
            unit.code if unit is not None else None,
            base_url=base_url,
            campus=campus,
        )
        if candidate is not None:
            key = (candidate.course_code, candidate.habilitation_code, candidate.unit_code)
            values[key] = candidate
    return tuple(
        sorted(values.values(), key=lambda item: (item.course_code, item.habilitation_code, item.name))
    )


def _credit_value(value: str) -> int | None:
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _source_code(value: str) -> str | None:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9_-]{2,31})(?:\s+-|\s*$)", value)
    if match is None:
        return None
    code = match.group(1)
    if not _CODE.fullmatch(code) or (code.isdigit() and len(code) < 5):
        return None
    return code


@dataclass(slots=True)
class _CurriculumItemState:
    ideal_period: str
    discipline_code: str
    item_type: str
    name: str | None
    aula_credits: int | None
    work_credits: int | None
    weak_prerequisites: list[str] = field(default_factory=list)
    strong_prerequisites: list[str] = field(default_factory=list)
    set_indications: list[str] = field(default_factory=list)


def _curriculum_metadata(
    soup: BeautifulSoup, candidate: CandidateCurriculum
) -> dict[str, str | None]:
    metadata: dict[str, str | None] = {
        "name": candidate.name,
        "campus": candidate.campus,
        "period": candidate.period_code,
    }
    for table in soup.find_all("table"):
        for row in _owned_rows(table):
            values = _cells(row)
            if not values:
                continue
            combined = " ".join(values).strip()
            course_match = re.match(r"\s*Curso\s*:\s*(.+)", combined, re.I)
            if course_match is not None:
                metadata["name"] = course_match.group(1).split(" - ", 1)[-1].strip()
            if len(values) != 2:
                continue
            label = _label(values[0])
            value = values[1].strip()
            if label in {"curso", "nome do curso", "nome"} and value:
                metadata["name"] = value.split(" - ", 1)[-1].strip()
            elif "campus" in label and value:
                metadata["campus"] = value
            elif label in {"periodo", "vigencia", "codigo do periodo"} and value:
                metadata["period"] = value
    return metadata


def _curriculum_nature(value: str) -> str | None:
    normalized = normalize_text(value)
    if "disciplinas" not in normalized:
        return None
    if "obrig" in normalized:
        return "obrigatoria"
    if "optat" in normalized and "livre" in normalized:
        return "livre"
    if "optat" in normalized and "eletiv" in normalized:
        return "eletiva"
    if "optat" in normalized:
        return "optativa"
    return None


def _curriculum_discipline_row(row: Tag) -> tuple[str, list[str]] | None:
    values = _cells(row)
    for link in row.find_all("a", href=True):
        if link.find_parent("tr") is not row:
            continue
        href = str(link.get("href", ""))
        if "obterdisciplina" not in href.casefold():
            continue
        params = _query(href)
        code = _first_parameter(params, "sgldis", "coddis", "coddisciplina")
        if code is None or not _CODE.fullmatch(code) or (code.isdigit() and len(code) < 5):
            continue
        displayed_code = _source_code(_text(link))
        if displayed_code is not None and displayed_code != code:
            continue
        return code, values
    return None


def parse_curriculum_detail(
    document: str | bytes,
    candidate: CandidateCurriculum,
) -> ParsedCurriculum:
    """Parse one current curriculum and its habilitation."""
    soup = _soup(document)
    metadata = _curriculum_metadata(soup, candidate)
    states: list[_CurriculumItemState] = []
    current_nature = "unknown"
    current_period = "unknown"
    current_item: _CurriculumItemState | None = None
    for table in soup.find_all("table"):
        for row in _owned_rows(table):
            values = _cells(row)
            row_text = " ".join(values)
            normalized_row = normalize_text(row_text)
            nature = _curriculum_nature(row_text)
            if nature is not None:
                current_nature = nature
                current_period = "unknown"
                current_item = None
                continue
            if "periodo ideal" in normalized_row:
                period_match = re.search(r"\d+", normalized_row)
                if period_match is not None:
                    current_period = period_match.group(0)
                current_item = None
                continue
            discipline_row = _curriculum_discipline_row(row)
            if discipline_row is not None:
                code, discipline_values = discipline_row
                code_index = next(
                    (
                        index
                        for index, value in enumerate(discipline_values)
                        if _source_code(value) == code
                    ),
                    0,
                )
                name = (
                    discipline_values[code_index + 1].strip()
                    if code_index + 1 < len(discipline_values)
                    and discipline_values[code_index + 1].strip()
                    else None
                )
                current_item = _CurriculumItemState(
                    current_period,
                    code,
                    current_nature,
                    name,
                    (
                        _credit_value(discipline_values[code_index + 2])
                        if code_index + 2 < len(discipline_values)
                        else None
                    ),
                    (
                        _credit_value(discipline_values[code_index + 3])
                        if code_index + 3 < len(discipline_values)
                        else None
                    ),
                )
                states.append(current_item)
                continue
            if current_item is None or normalized_row == "ou":
                continue
            if not any(value in normalized_row for value in ("requisito", "indicacao de conjunto")):
                continue
            prerequisite = _source_code(values[0]) if values else None
            if prerequisite is None:
                continue
            if "indicacao de conjunto" in normalized_row:
                target = current_item.set_indications
            elif "requisito fraco" in normalized_row:
                target = current_item.weak_prerequisites
            else:
                target = current_item.strong_prerequisites
            if prerequisite not in target:
                target.append(prerequisite)

    items = tuple(
        CurriculumItem(
            curriculum_id=f"curriculum:{candidate.course_code}:{candidate.habilitation_code}",
            ideal_period=item.ideal_period,
            discipline_code=item.discipline_code,
            item_type=item.item_type,
            weak_prerequisites=tuple(sorted(item.weak_prerequisites)),
            strong_prerequisites=tuple(sorted(item.strong_prerequisites)),
            set_indications=tuple(sorted(item.set_indications)),
            name=item.name,
            aula_credits=item.aula_credits,
            work_credits=item.work_credits,
        )
        for item in states
    )
    normalized_candidate = CandidateCurriculum(
        candidate.course_code,
        candidate.habilitation_code,
        str(metadata["name"] or candidate.name),
        candidate.unit_code,
        candidate.detail_url,
        metadata["campus"],
        metadata["period"],
    )
    return ParsedCurriculum(
        candidate=normalized_candidate,
        items=tuple(sorted(items, key=lambda item: (item.ideal_period, item.discipline_code))),
        source_campus_name=metadata["campus"],
        source_period_code=metadata["period"],
    )


def parse_discipline_detail(
    document: str | bytes,
    candidate: CandidateDiscipline,
    unit_code: str | None,
) -> Discipline:
    """Parse one discipline page using labels and their following content rows."""
    soup = _soup(document)
    name = candidate.name
    department: str | None = None
    aula_credits = 0
    work_credits = 0
    heading_content: dict[str, str] = {}

    for table in soup.find_all("table"):
        rows = _owned_rows(table)
        previous_nonempty: str | None = None
        pending_heading: str | None = None
        for row in rows:
            values = _cells(row)
            row_text = " ".join(values).strip()
            if not row_text:
                continue
            normalized_row = normalize_text(row_text).rstrip(":")
            title_match = re.match(
                rf"\s*Disciplina\s*:\s*{re.escape(candidate.code)}\s*-\s*(.+)",
                row_text,
                re.I,
            )
            if title_match is not None:
                name = title_match.group(1).strip()
                if department is None and previous_nonempty is not None:
                    department = previous_nonempty
                previous_nonempty = row_text
                pending_heading = None
                continue
            if len(values) >= 2:
                label = _label(values[0])
                value = " ".join(values[1:]).strip()
                if label == "disciplina" and value:
                    name = value.split("-", 1)[-1].strip()
                elif "creditos aula" in label:
                    aula_credits = _credit_value(value) or 0
                elif "creditos trabalho" in label:
                    work_credits = _credit_value(value) or 0
                elif "departamento" in label and value:
                    department = value
            department_match = re.match(r"\s*Departamento\s*:\s*(.+)", row_text, re.I)
            if department_match is not None:
                department = department_match.group(1).strip()

            heading = next(
                (
                    value
                    for value in ("ementa", "conteudo programatico", "objetivos")
                    if normalized_row == value
                ),
                None,
            )
            if heading is not None:
                pending_heading = heading
                previous_nonempty = row_text
                continue
            if pending_heading is not None:
                heading_content.setdefault(pending_heading, row_text)
                pending_heading = None
            previous_nonempty = row_text

    return Discipline(
        candidate.code,
        name,
        unit_code,
        department,
        candidate.verdis,
        aula_credits,
        work_credits,
        heading_content.get("objetivos"),
        heading_content.get("ementa") or heading_content.get("conteudo programatico"),
        False,
        candidate.unit_codes,
        candidate.verdis_seen or ((candidate.verdis,) if candidate.verdis else ()),
    )


def _date_value(value: str) -> date | None:
    for format_value in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value.strip(), format_value).date()
        except ValueError:
            pass
    return None


def _label(value: str) -> str:
    return normalize_text(value).rstrip(":")


def _field(rows: list[list[str]], *labels: str) -> str:
    wanted = {_label(item) for item in labels}
    for row in rows:
        if len(row) >= 2 and _label(row[0]) in wanted:
            return row[1]
    return ""


def _period(section_code: str, explicit: str) -> str:
    if explicit.strip():
        match = re.search(r"\d{5}", explicit)
        if match:
            return match.group(0)
    match = re.search(r"\d{5}", section_code)
    return match.group(0) if match else "unknown"


def _schedule(
    table: Tag, start_date: date | None, end_date: date | None
) -> tuple[tuple[Meeting, ...], str, tuple[str, ...]]:
    meetings: list[Meeting] = []
    current_day: str | None = None
    current_original_day: str | None = None
    current_start: str | None = None
    current_end: str | None = None
    professors: list[str] = []
    saw_row = False
    day_index, start_index, end_index = 0, 1, 2
    professor_index: int | None = 3
    header_found = False
    for row in _owned_rows(table):
        values = _cells(row)
        labels = [_label(value) for value in values]
        is_header = bool(labels) and (
            "horario" in labels[0]
            or (
                any("dia" in value for value in labels)
                and any("inicio" in value or "hora" in value for value in labels)
            )
        )
        if is_header:
            day_index = next(
                (index for index, value in enumerate(labels) if "dia" in value), 0
            )
            start_index = next(
                (index for index, value in enumerate(labels) if "inicio" in value),
                min(1, len(values) - 1),
            )
            end_index = next(
                (index for index, value in enumerate(labels) if "fim" in value or "termin" in value),
                min(start_index + 1, len(values) - 1),
            )
            professor_index = next(
                (
                    index
                    for index, value in enumerate(labels)
                    if value.startswith("prof") or "docente" in value
                ),
                min(end_index + 1, len(values) - 1) if values else None,
            )
            header_found = True
            continue
        if not header_found or not values:
            continue
        day_text = values[day_index] if day_index < len(values) else ""
        start_text = values[start_index] if start_index < len(values) else ""
        end_text = values[end_index] if end_index < len(values) else ""
        professor = (
            values[professor_index]
            if professor_index is not None and professor_index < len(values)
            else ""
        )
        if not any((day_text, start_text, end_text, professor)):
            continue
        saw_row = True
        if professor:
            professors.append(professor)
        if day_text:
            if current_day is not None:
                meetings.append(
                    _meeting(
                        current_day,
                        current_original_day,
                        current_start,
                        current_end,
                        start_date,
                        end_date,
                    )
                )
            current_day = normalize_day(day_text) or "unknown"
            current_original_day = day_text
            current_start, current_end = start_text, end_text
        elif current_day is not None:
            if start_text:
                meetings.append(
                    _meeting(
                        current_day,
                        current_original_day,
                        current_start,
                        current_end,
                        start_date,
                        end_date,
                    )
                )
                current_start, current_end = start_text, end_text
    if current_day is not None:
        meetings.append(
            _meeting(
                current_day,
                current_original_day,
                current_start,
                current_end,
                start_date,
                end_date,
            )
        )
    if not saw_row:
        return (), "unknown", ()
    status = "complete"
    if not meetings or any(
        item.day in {"", "unknown"}
        or item.start_minute is None
        or item.end_minute is None
        for item in meetings
    ):
        status = "partial"
    return tuple(meetings), status, tuple(professors)


def _meeting(
    day: str | None,
    original_day: str | None,
    start: str | None,
    end: str | None,
    first: date | None,
    last: date | None,
) -> Meeting:
    return Meeting(
        day or "unknown",
        parse_time(start),
        parse_time(end),
        first,
        last,
        start or "",
        end or "",
        original_day or "",
    )


def _vacancies(table: Tag, section_id: str, observed_at: str) -> tuple[Vacancy, ...]:
    result: list[Vacancy] = []
    rows = [_expanded_cells(row) for row in _owned_rows(table)]
    header = next((row for row in rows if any(_label(value) == "vagas" for value in row)), [])
    labels = [_label(value) for value in header]
    positions: dict[str, int | None] = {}
    for name in ("vagas", "inscritos", "pendentes", "matriculados"):
        matches = [index for index, label in enumerate(labels) if label == name]
        positions[name] = matches[-1] if matches else None
    current_category: str | None = None
    for values in rows:
        if not values or values == header:
            continue
        available_position = positions["vagas"]
        if available_position is None:
            continue
        category_value = values[0].strip() if values else ""
        group_value = values[1].strip() if len(values) > 1 else ""
        if category_value:
            current_category = category_value
            group_name = None
        elif group_value and current_category is not None:
            group_name = group_value
        else:
            continue

        result.append(
            Vacancy(
                section_id,
                current_category,
                group_name,
                _vacancy_value(values, positions, "vagas"),
                _vacancy_value(values, positions, "inscritos"),
                _vacancy_value(values, positions, "pendentes"),
                _vacancy_value(values, positions, "matriculados"),
                observed_at,
            )
        )
    return tuple(result)


def _vacancy_value(
    values: list[str], positions: dict[str, int | None], name: str
) -> str | None:
    position = positions[name]
    return values[position] if position is not None and position < len(values) else None


def parse_sections_page(
    document: str | bytes, discipline_code: str, observed_at: str = ""
) -> ParsedSections:
    soup = _soup(document)
    body_text = " ".join(soup.stripped_strings)
    if _NO_OFFER.search(normalize_text(body_text)):
        return ParsedSections("no_current_offer", message=body_text.strip())
    tables = soup.find_all("table")
    info_indices = [
        index
        for index, table in enumerate(tables)
        if any(
            _label(cell)
            in {"codigo da turma", "codigo da turma pratica", "codigo da turma teorica"}
            for row in _owned_rows(table)
            for cell in _cells(row)[:1]
        )
    ]
    if not info_indices:
        return ParsedSections("invalid_source", message="section table not found")
    sections: list[Section] = []
    vacancies: dict[str, tuple[Vacancy, ...]] = {}
    seen_section_ids: set[str] = set()
    for position, table_index in enumerate(info_indices):
        end_index = info_indices[position + 1] if position + 1 < len(info_indices) else len(tables)
        info_table = tables[table_index]
        rows = [_cells(row) for row in _owned_rows(info_table)]
        raw_code = _field(
            rows, "Código da Turma", "Código da Turma Prática", "Código da Turma Teórica"
        ).strip()
        if not raw_code:
            continue
        code = raw_code.split()[0]
        if not _CODE.fullmatch(code):
            continue
        first = _date_value(_field(rows, "Início", "Inicio"))
        last = _date_value(_field(rows, "Fim"))
        explicit_period = _field(
            rows,
            "Período",
            "Periodo",
            "Código do Período",
            "Codigo do Periodo",
            "Código Período",
            "Codigo Periodo",
        )
        period = _period(code, explicit_period)
        section_id = f"section:{discipline_code}:{code}"
        if section_id in seen_section_ids:
            return ParsedSections(
                "invalid_source", message=f"duplicate generated section id: {section_id}"
            )
        seen_section_ids.add(section_id)
        meetings: tuple[Meeting, ...] = ()
        status = "unknown"
        section_vacancies: tuple[Vacancy, ...] = ()
        professor_values: list[str] = []
        for child in tables[table_index + 1 : end_index]:
            child_values = [
                _label(value)
                for row in _owned_rows(child)
                for value in _cells(row)
            ]
            has_schedule_header = any("horario" in value for value in child_values) or (
                any("dia" in value for value in child_values)
                and any("inicio" in value or "hora" in value for value in child_values)
            )
            if has_schedule_header and any(
                parse_time(value) is not None
                for row in _owned_rows(child)
                for value in _cells(row)
            ):
                child_meetings, child_status, child_professors = _schedule(child, first, last)
                meetings += child_meetings
                professor_values.extend(child_professors)
                if status == "unknown":
                    status = child_status
                elif child_status != "complete":
                    status = "partial"
            elif "vagas" in child_values:
                section_vacancies += _vacancies(child, section_id, observed_at)
        by_professor: dict[str, Professor] = {}
        for value in professor_values:
            professor = Professor.from_source(value)
            existing = by_professor.get(professor.normalized_name)
            if existing is None or (professor.responsible and not existing.responsible):
                by_professor[professor.normalized_name] = professor
        professors = tuple(
            sorted(
                by_professor.values(),
                key=lambda item: (item.normalized_name, item.display_name, not item.responsible),
            )
        )
        section = Section(
            section_id,
            discipline_code,
            code,
            period,
            first,
            last,
            _field(rows, "Tipo da Turma", "Tipo") or "unknown",
            _field(rows, "Observações", "Observacoes"),
            status,
            meetings,
            professors,
            _field(rows, "Código da Turma Teórica", "Codigo da Turma Teorica") or None,
            ("schedule_incomplete",) if status != "complete" else (),
        )
        sections.append(section)
        vacancies[section_id] = section_vacancies
    if not sections:
        return ParsedSections("invalid_source", message="no parseable section")
    return ParsedSections("confirmed", tuple(sections), vacancies)
