"""Opt-in browser contract checks kept out of the production crawler."""

import os

import pytest


@pytest.mark.live_contract
def test_live_contract_is_explicitly_opt_in() -> None:
    """CI can enable the live suite without making normal tests networked."""
    if os.environ.get("MATRUSP_RUN_LIVE_CONTRACT") != "1":
        pytest.skip("set MATRUSP_RUN_LIVE_CONTRACT=1 to run the Playwright contract suite")
    from playwright.sync_api import sync_playwright

    raw_urls = os.environ.get(
        "MATRUSP_CONTRACT_URLS",
        "https://uspdigital.usp.br/jupiterweb/jupColegiadoLista?tipo=T,"
        "https://uspdigital.usp.br/jupiterweb/jupDisciplinaLista?tipo=T&codcg=45,"
        "https://uspdigital.usp.br/jupiterweb/obterTurma?print=true&sgldis=MAC0101,"
        "https://uspdigital.usp.br/jupiterweb/jupCursoLista?tipo=N&codcg=45",
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        for url in (item.strip() for item in raw_urls.split(",")):
            response = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            assert response is not None and response.status < 500
            content = page.content().strip()
            assert content
            assert "<html" in content.casefold()
            # A structural contract failure must be visible to CI rather than silently
            # publishing an empty snapshot.
            assert "<table" in content.casefold() or "não existem" in content.casefold() or "nao existem" in content.casefold()
        browser.close()
