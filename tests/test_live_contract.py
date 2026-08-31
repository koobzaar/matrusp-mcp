"""Opt-in browser contract checks kept out of the production crawler."""

import os

import pytest

from matrusp_mcp.crawler.models import CandidateCurriculum
from matrusp_mcp.crawler.parsers import (
    parse_curriculum_detail,
    parse_curriculum_index,
    parse_discipline_detail,
    parse_discipline_index,
    parse_sections_page,
    parse_units,
)


@pytest.mark.live_contract
def test_live_contract_is_explicitly_opt_in() -> None:
    """CI can enable the live suite without making normal tests networked."""
    if os.environ.get("MATRUSP_RUN_LIVE_CONTRACT") != "1":
        pytest.skip("set MATRUSP_RUN_LIVE_CONTRACT=1 to run the Playwright contract suite")
    from playwright.sync_api import sync_playwright

    raw_urls = os.environ.get(
        "MATRUSP_CONTRACT_URLS",
        "https://uspdigital.usp.br/jupiterweb/jupColegiadoLista?tipo=T,"
        "https://uspdigital.usp.br/jupiterweb/jupDisciplinaLista?letra=A-Z&tipo=T&codcg=45,"
        "https://uspdigital.usp.br/jupiterweb/obterTurma?print=true&sgldis=AGA0215,"
        "https://uspdigital.usp.br/jupiterweb/jupCursoLista?tipo=N&codcg=45",
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            user_agent="MatrUSP-MCP/0.1 (+https://github.com/matrusp/matrusp-mcp)"
        )
        contents: list[str] = []
        for url in (item.strip() for item in raw_urls.split(",")):
            response = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            assert response is not None and response.status < 500
            content = page.content().strip()
            assert content
            assert "<html" in content.casefold()
            contents.append(content)

        assert len(contents) == 4
        units = parse_units(contents[0])
        unit = next(item for item in units if item.code == "45")
        disciplines = parse_discipline_index(contents[1], unit)
        assert disciplines

        sections = parse_sections_page(contents[2], "AGA0215")
        assert sections.status == "confirmed"
        assert len({item.id for item in sections.sections}) == len(sections.sections)
        meetings = [meeting for section in sections.sections for meeting in section.meetings]
        assert meetings
        assert all(
            meeting.day != "unknown"
            and meeting.start_minute is not None
            and meeting.end_minute is not None
            and meeting.start_minute < meeting.end_minute
            for meeting in meetings
        )

        curriculum_candidates = parse_curriculum_index(contents[3], unit)
        curriculum_candidate = next(
            item
            for item in curriculum_candidates
            if item.course_code == "45052" and item.habilitation_code == "0"
        )
        assert curriculum_candidate.campus
        assert curriculum_candidate.period_code == "integral"
        assert curriculum_candidate.detail_url is not None
        response = page.goto(
            curriculum_candidate.detail_url, wait_until="domcontentloaded", timeout=60_000
        )
        assert response is not None and response.status < 500
        curriculum = parse_curriculum_detail(page.content(), curriculum_candidate)
        assert curriculum.status == "confirmed"
        assert len(curriculum.items) >= 10
        assert all(item.discipline_code != "ATPA" for item in curriculum.items)

        regression_candidate = CandidateCurriculum(
            "3057",
            "3000",
            "Habilitação: Engenharia de Petróleo",
            "3",
            "https://uspdigital.usp.br/jupiterweb/"
            "listarGradeCurricular?codcg=3&codcur=3057&codhab=3000&tipo=N",
            "São Paulo - Cidade Universitária",
            "integral",
        )
        response = page.goto(
            regression_candidate.detail_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        assert response is not None and response.status < 500
        regression = parse_curriculum_detail(page.content(), regression_candidate)
        assert regression.status in {"confirmed", "no_current_curriculum"}
        assert bool(regression.items) is (regression.status == "confirmed")

        discipline_candidate = next(item for item in disciplines if item.code == "MAC0110")
        response = page.goto(
            "https://uspdigital.usp.br/jupiterweb/obterDisciplina?print=true&sgldis=MAC0110",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        assert response is not None and response.status < 500
        discipline = parse_discipline_detail(page.content(), discipline_candidate, unit.code)
        assert discipline.name != discipline.code
        assert discipline.aula_credits > 0
        assert discipline.summary
        browser.close()
