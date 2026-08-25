"""Parsers semânticos e tolerantes para as páginas HTML do JupiterWeb."""

from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from ..domain import CurriculumItem, Meeting, Professor, Section, Vacancy
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
    r"(?:n[aã]o\s+(?:existem|h[aá])\s+(?:turmas?|ofertas?)|sem\s+(?:turmas?|ofertas?)|"
    r"nenhum(?:a)?\s+(?:turma|oferta)|n[aã]o\s+foram\s+encontrad[ao]s?\s+turmas?|"
    r"n[aã]o\s+h[aá]\s+oferta|oferta\s+inexistente)",
    re.I,
)


def _soup(document: str | bytes) -> BeautifulSoup:
    return BeautifulSoup(document, "html5lib")


def _text(node: Tag) -> str:
    return " ".join(node.stripped_strings).strip()


def _cells(row: Tag) -> list[str]:
    return [_text(cell) for cell in row.find_all(["th", "td"], recursive=False)]


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
    link: Tag, unit_code: str | None, *, base_url: str = "https://uspdigital.usp.br/jupiterweb/"
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
        campus=None,
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
    values: dict[tuple[str, str, str | None], CandidateCurriculum] = {}
    for link in soup.find_all(["a", "option"]):
        candidate = _curriculum_candidate_from_link(
            link, unit.code if unit is not None else None, base_url=base_url
        )
        if candidate is not None:
            key = (candidate.course_code, candidate.habilitation_code, candidate.unit_code)
            values[key] = candidate
    return tuple(
        sorted(values.values(), key=lambda item: (item.course_code, item.habilitation_code, item.name))
    )


def _validated_codes(value: str) -> tuple[str, ...]:
    tokens = {
        token
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,31}", value)
        if (_CODE.fullmatch(token) is not None)
        and (not token.isdigit() or len(token) >= 5)
        and (any(char.isdigit() for char in token) or token.upper() == token)
    }
    return tuple(sorted(tokens, key=lambda token: (not any(char.isdigit() for char in token), token)))


def _item_type(value: str) -> str:
    normalized = normalize_text(value)
    if "optat" in normalized:
        return "optativa"
    if "eletiv" in normalized:
        return "eletiva"
    if "livre" in normalized:
        return "livre"
    if "obrig" in normalized or "basica" in normalized:
        return "obrigatoria"
    return value.strip() or "unknown"


def _credit_value(value: str) -> int | None:
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def parse_curriculum_detail(
    document: str | bytes,
    candidate: CandidateCurriculum,
) -> ParsedCurriculum:
    """Parse one current curriculum and its habilitation."""
    soup = _soup(document)
    rows = [
        [_text(cell) for cell in row.find_all(["th", "td"], recursive=False)]
        for row in soup.find_all("tr")
    ]
    rows = [row for row in rows if row]
    metadata: dict[str, str | None] = {
        "name": candidate.name,
        "campus": candidate.campus,
        "period": candidate.period_code,
    }
    for row in rows:
        if len(row) != 2:
            continue
        label = _label(row[0])
        value = row[1].strip()
        if label in {"curso", "nome do curso", "nome"} and value:
            metadata["name"] = value.split(" - ", 1)[-1].strip()
        elif "campus" in label and value:
            metadata["campus"] = value
        elif "periodo" in label or "vigencia" in label:
            metadata["period"] = value or metadata["period"]

    items: list[CurriculumItem] = []
    for table in soup.find_all("table"):
        table_rows = [
            [_text(cell) for cell in row.find_all(["th", "td"], recursive=False)]
            for row in table.find_all("tr")
        ]
        table_rows = [row for row in table_rows if row]
        if not table_rows:
            continue
        header_index = next(
            (
                index
                for index, row in enumerate(table_rows[:3])
                if any("disciplina" in _label(value) or "codigo" in _label(value) for value in row)
            ),
            0,
        )
        headers = [_label(value) for value in table_rows[header_index]]
        if not any("disciplina" in value or "codigo" in value for value in headers):
            continue
        code_index = next(
            (index for index, value in enumerate(headers) if "codigo" in value or "disciplina" in value),
            0,
        )
        period_index = next(
            (index for index, value in enumerate(headers) if "periodo" in value or "semestre" in value),
            0,
        )
        nature_index = next(
            (index for index, value in enumerate(headers) if "natureza" in value or "tipo" in value),
            min(2, len(headers) - 1),
        )
        prerequisite_index = next(
            (index for index, value in enumerate(headers) if "requis" in value or "depend" in value),
            None,
        )
        aula_index = next(
            (index for index, value in enumerate(headers) if "credito aula" in value or "creditos aula" in value), None
        )
        work_index = next(
            (index for index, value in enumerate(headers) if "credito trabalho" in value or "creditos trabalho" in value), None
        )
        for row in table_rows[header_index + 1 :]:
            if code_index >= len(row):
                continue
            codes = _validated_codes(row[code_index]) or _validated_codes(" ".join(row))[:1]
            if not codes:
                continue
            code = codes[0]
            ideal_period = row[period_index].strip() if period_index < len(row) else ""
            nature = _item_type(row[nature_index] if nature_index < len(row) else "")
            requirement_text = (
                row[prerequisite_index]
                if prerequisite_index is not None and prerequisite_index < len(row)
                else ""
            )
            strong_values: list[str] = []
            weak_values: list[str] = []
            set_values: list[str] = []
            for part in re.split(r"[,;]", requirement_text):
                part_codes = _validated_codes(part)
                normalized_part = normalize_text(part)
                if "fort" in normalized_part:
                    strong_values.extend(part_codes)
                elif "frac" in normalized_part:
                    weak_values.extend(part_codes)
                elif "conjunto" in normalized_part or "grupo" in normalized_part:
                    set_values.extend(part_codes)
            strong = tuple(strong_values) if strong_values else ()
            weak = tuple(weak_values) if weak_values else ()
            sets = tuple(set_values) if set_values else ()
            raw_item = row[code_index]
            item_name = raw_item.split(" - ", 1)[-1].strip() if " - " in raw_item else None
            if item_name is None:
                item_name = next(
                    (
                        value.strip()
                        for index, value in enumerate(row)
                        if index != code_index and value.strip() and not _validated_codes(value)
                    ),
                    None,
                )
            items.append(
                CurriculumItem(
                    curriculum_id=f"curriculum:{candidate.course_code}:{candidate.habilitation_code}",
                    ideal_period=ideal_period or "unknown",
                    discipline_code=code,
                    item_type=nature,
                    weak_prerequisites=tuple(weak),
                    strong_prerequisites=tuple(strong),
                    set_indications=tuple(sets),
                    name=item_name,
                    aula_credits=(
                        _credit_value(row[aula_index])
                        if aula_index is not None and aula_index < len(row)
                        else None
                    ),
                    work_credits=(
                        _credit_value(row[work_index])
                        if work_index is not None and work_index < len(row)
                        else None
                    ),
                )
            )
    unique = {
        (item.ideal_period, item.discipline_code, item.item_type): item for item in items
    }
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
        items=tuple(sorted(unique.values(), key=lambda item: (item.ideal_period, item.discipline_code))),
        source_campus_name=metadata["campus"],
        source_period_code=metadata["period"],
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
) -> tuple[tuple[Meeting, ...], str]:
    meetings: list[Meeting] = []
    current_day: str | None = None
    current_start: str | None = None
    current_end: str | None = None
    current_professors: list[str] = []
    saw_row = False
    day_index, start_index, end_index, professor_index = 0, 1, 2, 3
    header_found = False
    for row in table.find_all("tr"):
        values = _cells(row)
        labels = [_label(value) for value in values]
        if any("dia" in value for value in labels) and any(
            "inicio" in value or "hora" in value for value in labels
        ):
            day_index = next((index for index, value in enumerate(labels) if "dia" in value), 0)
            start_index = next(
                (index for index, value in enumerate(labels) if "inicio" in value or "hora" in value),
                min(1, len(values) - 1),
            )
            end_index = next(
                (index for index, value in enumerate(labels) if "fim" in value or "termin" in value),
                min(start_index + 1, len(values) - 1),
            )
            professor_index = next(
                (index for index, value in enumerate(labels) if "professor" in value or "docente" in value),
                min(end_index + 1, len(values) - 1),
            )
            header_found = True
            continue
        if len(values) <= max(day_index, start_index, end_index, professor_index) or (
            not header_found and _label(values[0]) in {"horario", "dia"}
        ):
            continue
        saw_row = True
        day_text = values[day_index]
        start_text = values[start_index]
        end_text = values[end_index]
        professor = values[professor_index]
        if day_text:
            if current_day is not None:
                meetings.append(
                    _meeting(
                        current_day,
                        current_start,
                        current_end,
                        current_professors,
                        start_date,
                        end_date,
                    )
                )
            current_day = normalize_day(day_text)
            current_start, current_end = start_text, end_text
            current_professors = [professor] if professor else []
        elif current_day is not None:
            if start_text:
                meetings.append(
                    _meeting(
                        current_day,
                        current_start,
                        current_end,
                        current_professors,
                        start_date,
                        end_date,
                    )
                )
                current_start, current_end = start_text, end_text
                current_professors = [professor] if professor else []
            elif professor:
                current_professors.append(professor)
    if current_day is not None:
        meetings.append(
            _meeting(
                current_day, current_start, current_end, current_professors, start_date, end_date
            )
        )
    status = "complete"
    if not saw_row:
        return (), "unknown"
    if any(
        item.day in {"", "unknown"}
        or item.start_minute is None
        or item.end_minute is None
        for item in meetings
    ):
        status = "partial"
    return tuple(meetings), status


def _meeting(
    day: str | None,
    start: str | None,
    end: str | None,
    professors: list[str],
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
        day or "",
    )


def _vacancies(table: Tag, section_id: str, observed_at: str) -> tuple[Vacancy, ...]:
    result: list[Vacancy] = []
    rows = [_cells(row) for row in table.find_all("tr")]
    header = next(
        (
            row
            for row in rows
            if row and _label(row[0]) in {"vagas", "tipo", "categoria"}
        ),
        [],
    )
    labels = [_label(value) for value in header]
    defaults = {"vagas": 1, "inscritos": 2, "pendentes": 3, "matriculados": 4}
    positions = {}
    for name, fallback in defaults.items():
        matches = [index for index, label in enumerate(labels) if label == name]
        positions[name] = matches[-1] if name == "vagas" and len(matches) > 1 else (
            matches[0] if matches else fallback
        )
    for values in rows:
        if not values or not values[0] or _label(values[0]) in {"vagas", "tipo", "categoria"}:
            continue

        result.append(
            Vacancy(
                section_id,
                values[0],
                None,
                values[positions["vagas"]] if positions["vagas"] < len(values) else None,
                values[positions["inscritos"]]
                if positions["inscritos"] < len(values)
                else None,
                values[positions["pendentes"]]
                if positions["pendentes"] < len(values)
                else None,
                values[positions["matriculados"]]
                if positions["matriculados"] < len(values)
                else None,
                observed_at,
            )
        )
    return tuple(result)


def parse_sections_page(
    document: str | bytes, discipline_code: str, observed_at: str = ""
) -> ParsedSections:
    soup = _soup(document)
    body_text = " ".join(soup.stripped_strings)
    if _NO_OFFER.search(body_text):
        return ParsedSections("no_current_offer", message=body_text.strip())
    tables = soup.find_all("table")
    info_indices = [
        index
        for index, table in enumerate(tables)
        if any(
            _label(cell)
            in {"codigo da turma", "codigo da turma pratica", "codigo da turma teorica"}
            for row in table.find_all("tr")
            for cell in _cells(row)[:1]
        )
    ]
    if not info_indices:
        return ParsedSections("invalid_source", message="section table not found")
    sections: list[Section] = []
    vacancies: dict[str, tuple[Vacancy, ...]] = {}
    for position, table_index in enumerate(info_indices):
        end_index = info_indices[position + 1] if position + 1 < len(info_indices) else len(tables)
        info_table = tables[table_index]
        rows = [_cells(row) for row in info_table.find_all("tr")]
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
        meetings: tuple[Meeting, ...] = ()
        status = "unknown"
        section_vacancies: tuple[Vacancy, ...] = ()
        for child in tables[table_index:end_index]:
            child_text = normalize_text(_text(child))
            child_values = [
                _label(value)
                for row in child.find_all("tr")
                for value in _cells(row)
            ]
            has_schedule_header = "horario" in child_text or (
                any("dia" in value for value in child_values)
                and any("inicio" in value or "hora" in value for value in child_values)
            )
            if has_schedule_header and any(
                parse_time(value) is not None
                for row in child.find_all("tr")
                for value in _cells(row)
            ):
                child_meetings, child_status = _schedule(child, first, last)
                meetings += child_meetings
                if status == "unknown":
                    status = child_status
                elif child_status != "complete":
                    status = "partial"
            elif "vagas" in child_text:
                section_vacancies = _vacancies(child, section_id, observed_at)
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
            (),
            _field(rows, "Código da Turma Teórica", "Codigo da Turma Teorica") or None,
            ("schedule_incomplete",) if status != "complete" else (),
        )
        # Professor names are carried by the source meeting rows; preserve them as section-level values too.
        professor_values: list[str] = []
        for child in tables[table_index:end_index]:
            child_labels = {
                _label(value)
                for row in child.find_all("tr")
                for value in _cells(row)
            }
            if "horario" not in normalize_text(_text(child)) and not any(
                "professor" in value or "docente" in value for value in child_labels
            ):
                continue
            for row in child.find_all("tr"):
                values = _cells(row)
                if len(values) < 2:
                    continue
                labels = [_label(value) for value in values]
                professor_index = next(
                    (index for index, value in enumerate(labels) if "professor" in value or "docente" in value),
                    3 if len(values) > 3 else None,
                )
                if professor_index is not None and professor_index < len(values):
                    value = values[professor_index]
                    if value and _label(value) not in {"professor", "docente"}:
                        professor_values.append(value)
        professors = tuple(Professor.from_source(value) for value in professor_values)
        section = Section(
            section.id,
            section.discipline_code,
            section.section_code,
            section.period_code,
            section.start_date,
            section.end_date,
            section.section_type,
            section.notes,
            section.schedule_status,
            section.meetings,
            professors,
            section.linked_theory_section_code,
            section.data_quality_flags,
        )
        sections.append(section)
        vacancies[section_id] = section_vacancies
    if not sections:
        return ParsedSections("invalid_source", message="no parseable section")
    return ParsedSections("confirmed", tuple(sections), vacancies)
