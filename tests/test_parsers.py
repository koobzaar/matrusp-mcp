from matrusp_mcp.crawler.models import CandidateCurriculum, CandidateDiscipline, UnitCandidate
from matrusp_mcp.crawler.parsers import (
    deduplicate_candidates,
    parse_curriculum_detail,
    parse_curriculum_index,
    parse_discipline_index,
    parse_sections_page,
    parse_units,
)


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


def test_explicit_no_offer_is_classified_without_parse_error() -> None:
    parsed = parse_sections_page(
        "<html><body>Não existem turmas para esta disciplina no período informado.</body></html>",
        "MAC0001",
    )
    assert parsed.status == "no_current_offer"
    assert parsed.sections == ()


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


def test_curriculum_detail_extracts_metadata_items_nature_credits_and_requirement_sets() -> None:
    candidate = CandidateCurriculum("CC", "Bach", "Curso antigo", "45")
    parsed = parse_curriculum_detail(
        """
        <table>
          <tr><td>Curso</td><td>CC - Curso atual</td></tr>
          <tr><td>Campus</td><td>São Carlos</td></tr>
          <tr><td>Vigência</td><td>20262</td></tr>
        </table>
        <table>
          <tr><th>Período ideal</th><th>Código da Disciplina</th><th>Natureza</th>
              <th>Requisitos</th><th>Créditos Aula</th><th>Créditos Trabalho</th></tr>
          <tr><td>1</td><td>MAC0001 - Introdução</td><td>Obrigatória</td>
              <td>MAC0002 (forte), MAC0003 (fraca), MAC0004 (conjunto)</td><td>4</td><td>2</td></tr>
          <tr><td>2</td><td>MAC0005 - Eletiva</td><td>Eletiva</td><td></td><td>-</td><td>-</td></tr>
          <tr><td>3</td><td>MAC0006</td><td>Optativa</td><td></td><td>3</td><td>0</td></tr>
        </table>
        """,
        candidate,
    )
    assert parsed.candidate.name == "Curso atual"
    assert parsed.source_campus_name == "São Carlos"
    assert parsed.source_period_code == "20262"
    assert [item.discipline_code for item in parsed.items] == ["MAC0001", "MAC0005", "MAC0006"]
    first = parsed.items[0]
    assert first.strong_prerequisites == ("MAC0002",)
    assert first.weak_prerequisites == ("MAC0003",)
    assert first.set_indications == ("MAC0004",)
    assert first.aula_credits == 4 and first.work_credits == 2


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
