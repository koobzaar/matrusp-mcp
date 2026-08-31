from pathlib import Path

import pytest

from matrusp_mcp.crawler.models import CandidateCurriculum, CandidateDiscipline, UnitCandidate
from matrusp_mcp.crawler.parsers import (
    deduplicate_candidates,
    parse_curriculum_detail,
    parse_curriculum_index,
    parse_discipline_detail,
    parse_discipline_index,
    parse_sections_page,
    parse_units,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_units_and_candidates_accept_unquoted_attributes_and_numeric_codes() -> None:
    units = parse_units(
        b"<a href=jupColegiadoMenu.jsp?codcg=45&tipo=D&nomclg=IME> Instituto de Matem\xe1tica </a>"
    )
    assert [(unit.code, unit.name) for unit in units] == [("45", "Instituto de Matemática")]
    candidates = parse_discipline_index(
        "<a href='obterTurma?sgldis=1234567&verdis=2'>Cálculo</a>", units[0]
    )
    assert candidates[0].code == "1234567"
    assert candidates[0].verdis == "2"


def test_candidates_are_globally_deduplicated_preserving_origins_and_versions() -> None:
    items = [
        CandidateDiscipline(code="MAC0001", name="Intro", verdis="1", unit_codes=("45",)),
        CandidateDiscipline(code="MAC0001", name="Intro", verdis="1", unit_codes=("27",)),
        CandidateDiscipline(code="MAC0001", name="Intro", verdis="2", unit_codes=("45",)),
    ]
    assert deduplicate_candidates(items) == (
        CandidateDiscipline(
            code="MAC0001",
            name="Intro",
            verdis="2",
            unit_codes=("27", "45"),
            verdis_seen=("1", "2"),
        ),
    )


@pytest.mark.parametrize(
    "message",
    (
        "Não existem turmas para esta disciplina no período informado.",
        "Nao existe oferecimento para a sigla MAC0001",
        "Não existe oferecimento para a sigla MAC0001",
    ),
)
def test_explicit_no_offer_is_classified_without_parse_error(message: str) -> None:
    parsed = parse_sections_page(f"<html><body>{message}</body></html>", "MAC0001")
    assert parsed.status == "no_current_offer"
    assert parsed.sections == ()


def test_current_mojibake_no_offer_is_classified_without_parse_error() -> None:
    assert parse_sections_page(fixture("no_offer.html"), "MAC0101").status == "no_current_offer"


def test_section_state_does_not_leak_schedule_or_vacancies() -> None:
    html = """
    <table><tr><td>Código da Turma</td><td>20262A</td></tr>
      <tr><td>Início</td><td>01/08/2026</td></tr><tr><td>Fim</td><td>20/12/2026</td></tr></table>
    <table><tr><td>Horário</td><td>Início</td><td>Fim</td><td>Professor</td></tr>
      <tr><td>seg</td><td>10:00</td><td>12:00</td><td>(R) Ada</td></tr></table>
    <table><tr><td>Vagas</td><td>Vagas</td><td>Inscritos</td><td>Pendentes</td><td>Matriculados</td></tr>
      <tr><td>Optativa</td><td>10</td><td>4</td><td>1</td><td>3</td></tr></table>
    <table><tr><td>Código da Turma</td><td>20263B</td></tr>
      <tr><td>Início</td><td>02/08/2026</td></tr><tr><td>Fim</td><td></td></tr></table>
    """
    parsed = parse_sections_page(html, "MAC0001")
    assert parsed.status == "confirmed"
    assert [section.period_code for section in parsed.sections] == ["20262", "20263"]
    assert parsed.sections[0].schedule_status == "complete"
    assert parsed.sections[1].schedule_status == "unknown"
    assert parsed.sections[1].meetings == ()
    assert parsed.vacancies[parsed.sections[0].id][0].available_text == "10"
    assert parsed.vacancies[parsed.sections[1].id] == ()


def test_nested_sections_preserve_schedule_rows_professors_days_and_grouped_vacancies() -> None:
    parsed = parse_sections_page(fixture("offering_nested.html"), "MAC0001", "observed")
    assert parsed.status == "confirmed"
    assert [section.id for section in parsed.sections] == [
        "section:MAC0001:2026201",
        "section:MAC0001:2026202",
    ]
    first, second = parsed.sections
    assert [(item.day, item.original_day) for item in first.meetings] == [
        ("mon", "seg"),
        ("mon", "seg"),
    ]
    assert [item.display_name for item in first.professors] == ["Ada Lovelace", "Grace Hopper"]
    assert first.professors[0].responsible is True
    assert all(item.display_name != "Prof(a) ." for item in first.professors)
    assert [(item.day, item.original_day) for item in second.meetings] == [
        ("tue", "terça-feira")
    ]
    first_vacancies = parsed.vacancies[first.id]
    assert [(item.category, item.group_name) for item in first_vacancies] == [
        ("Optativa Eletiva", None),
        ("Optativa Eletiva", "IME - Ciência da Computação"),
    ]
    assert first_vacancies[1].available_text == "20"
    second_vacancy = parsed.vacancies[second.id][0]
    assert second_vacancy.registered_text is None
    assert second_vacancy.pending_text is None
    assert second_vacancy.enrolled_text == "35"


def test_duplicate_generated_section_ids_are_invalid_source() -> None:
    html = """
    <table><tr><td>Código da Turma</td><td>2026201</td></tr></table>
    <table><tr><td>Código da Turma</td><td>2026201</td></tr></table>
    """
    parsed = parse_sections_page(html, "MAC0001")
    assert parsed.status == "invalid_source"
    assert parsed.message == "duplicate generated section id: section:MAC0001:2026201"


def test_missing_or_changed_tables_are_invalid_source() -> None:
    assert (
        parse_sections_page(
            "<html><table><tr><td>unexpected</td></tr></table></html>", "MAC0001"
        ).status
        == "invalid_source"
    )


def test_current_curriculum_index_supports_links_options_and_rejects_historical_links() -> None:
    values = parse_curriculum_index(
        """
        <a href="jupCurso?codcur=CC&codhab=Bacharelado&periodo=2026">Ciência</a>
        <a href="jupCurso?codcur=CC&codhab=Bacharelado&periodo=2026">duplicada</a>
        <option value="CC:Lic">Licenciatura</option>
        <a href="jupCursoLista?tipo=V&codcur=OLD&codhab=1">Histórico</a>
        <a href="other?codcur=NOPE">sem habilitação</a>
        """,
        UnitCandidate("45", "IME", "Cidade Universitária"),
    )
    assert [(item.course_code, item.habilitation_code) for item in values] == [
        ("CC", "Bacharelado"),
        ("CC", "Lic"),
    ]
    assert values[0].unit_code == "45"
    assert values[0].campus == "Cidade Universitária"
    assert values[0].name == "Ciência"


def test_curriculum_index_reads_real_adjacent_name_and_period_cells() -> None:
    parsed = parse_curriculum_index(
        """
        <table>
          <tr><td>Campus: São Paulo - Cidade Universitária</td></tr>
          <tr>
            <td><a href="listarGradeCurricular?codcg=3&codcur=3057&codhab=3000&tipo=N">
              3057 3000
            </a></td>
            <td>Habilitação: Engenharia de Petróleo</td>
            <td>integral</td>
          </tr>
        </table>
        """,
        UnitCandidate("3", "Escola Politécnica"),
    )

    assert len(parsed) == 1
    assert parsed[0].name == "Habilitação: Engenharia de Petróleo"
    assert parsed[0].period_code == "integral"


def test_curriculum_index_extracts_source_campus_metadata() -> None:
    parsed = parse_curriculum_index(
        """
        <table><tr><td>Campus: São Paulo - Cidade Universitária</td></tr></table>
        <a href="listarGradeCurricular?codcur=45052&codhab=0">Computação</a>
        """,
        UnitCandidate("45", "IME"),
    )
    assert parsed[0].campus == "São Paulo - Cidade Universitária"


def test_curriculum_detail_tracks_nature_period_items_and_following_requirements() -> None:
    candidate = CandidateCurriculum(
        "CC", "Bach", "Curso antigo", "45", campus="São Carlos", period_code="20262"
    )
    parsed = parse_curriculum_detail(fixture("curriculum.html"), candidate)
    assert parsed.candidate.name == "Ciência da Computação"
    assert parsed.source_campus_name == "São Carlos"
    assert parsed.source_period_code == "20262"
    assert [item.discipline_code for item in parsed.items] == ["MAC0001", "1234567", "MAC0999"]
    first = parsed.items[0]
    assert first.strong_prerequisites == ("MAC0002",)
    assert first.weak_prerequisites == ("1234567",)
    assert first.set_indications == ("MAC0003",)
    assert first.aula_credits == 4 and first.work_credits == 2
    assert [(item.ideal_period, item.item_type) for item in parsed.items] == [
        ("1", "obrigatoria"),
        ("2", "obrigatoria"),
        ("unknown", "livre"),
    ]
    assert "ATPA" not in {item.discipline_code for item in parsed.items}


def test_real_empty_curriculum_is_distinguished_from_unrecognized_html() -> None:
    candidate = CandidateCurriculum(
        "3057", "3000", "Habilitação: Engenharia de Petróleo", "3", period_code="integral"
    )

    explicit_empty = parse_curriculum_detail(
        fixture("curriculum_empty_3057_3000.html"), candidate
    )
    unrecognized = parse_curriculum_detail(
        "<html><table><tr><td>Grade Curricular</td></tr></table></html>", candidate
    )

    assert explicit_empty.status == "no_current_curriculum"
    assert explicit_empty.items == ()
    assert unrecognized.status == "invalid_source"


def test_discipline_detail_uses_heading_content_and_prefers_ementa() -> None:
    candidate = CandidateDiscipline("MAC0001", "Nome antigo", "3", ("45",))
    parsed = parse_discipline_detail(fixture("discipline_detail.html"), candidate, "45")
    assert parsed.name == "Introdução à Computação"
    assert parsed.department == "Ciência da Computação"
    assert parsed.aula_credits == 4 and parsed.work_credits == 2
    assert parsed.objectives == "Ensinar fundamentos."
    assert parsed.summary == "Resumo preferido."
    assert parsed.is_stub is False


def test_discipline_detail_tolerates_absent_optional_headings_and_uses_summary_fallback() -> None:
    candidate = CandidateDiscipline("MAC0002", "Nome antigo", None, ("45",))
    parsed = parse_discipline_detail(
        """
        <table><tr><td>Disciplina: MAC0002 - Estruturas</td></tr></table>
        <table><tr><td>Conteúdo Programático</td></tr><tr><td>Listas e árvores.</td></tr></table>
        """,
        candidate,
        "45",
    )
    assert parsed.name == "Estruturas"
    assert parsed.department is None
    assert parsed.objectives is None
    assert parsed.summary == "Listas e árvores."
    assert parsed.aula_credits == 0 and parsed.work_credits == 0


def test_schedule_parser_handles_changed_headers_and_partial_rows() -> None:
    parsed = parse_sections_page(
        """
        <table><tr><td>Código da Turma</td><td>20262A</td></tr>
          <tr><td>Início</td><td>2026-08-01</td></tr><tr><td>Fim</td><td>20/12/2026</td></tr>
        </table>
        <table><tr><th>Dia da semana</th><th>Hora início</th><th>Hora fim</th><th>Docente</th></tr>
          <tr><td>segunda-feira</td><td>10:00</td><td>12:00</td><td>(R) Ada</td></tr>
          <tr><td></td><td>13:00</td><td></td><td>Bob</td></tr>
        </table>
        """,
        "MAC0001",
    )
    assert parsed.status == "confirmed"
    assert parsed.sections[0].schedule_status == "partial"
    assert len(parsed.sections[0].meetings) == 2
    assert parsed.sections[0].professors[0].responsible is True
