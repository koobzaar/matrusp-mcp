import asyncio
from pathlib import Path

import pytest

from matrusp_mcp.crawler.crawler import CrawlError, FetchPolicy, JupiterCrawler
from matrusp_mcp.crawler.models import CandidateCurriculum, CandidateDiscipline
from matrusp_mcp.repository import Repository
from matrusp_mcp.snapshot import build_snapshot

FIXTURES = Path(__file__).parent / "fixtures"


def test_policy_bounds_concurrency_timeout_and_user_agent() -> None:
    policy = FetchPolicy(concurrency=8)
    assert policy.timeout_seconds == 60
    assert policy.attempts == 4
    assert "MatrUSP" in policy.user_agent
    with pytest.raises(ValueError):
        FetchPolicy(concurrency=17)
    with pytest.raises(ValueError):
        FetchPolicy(timeout_seconds=61)


@pytest.mark.asyncio
async def test_retry_backoff_and_tls_are_used_without_leaking_source_arguments() -> None:
    calls: list[tuple[str, bool, float]] = []
    sleeps: list[float] = []

    async def fetch(url: str, verify: bool, timeout: float) -> tuple[int, bytes]:
        calls.append((url, verify, timeout))
        if len(calls) < 4:
            raise TimeoutError("temporary")
        return 200, b"ok"

    crawler = JupiterCrawler(fetcher=fetch, sleep=lambda seconds: sleeps.append(seconds))
    status, body = await crawler._fetch_with_retry("https://example.test")
    assert status == 200 and body == b"ok"
    assert len(calls) == 4 and all(call[1] is True for call in calls)
    assert sleeps == sorted(sleeps) and len(sleeps) == 3


@pytest.mark.asyncio
async def test_retry_shares_url_timeout_budget_across_all_attempts() -> None:
    timeouts: list[float] = []

    async def fetch(url: str, verify: bool, timeout: float) -> tuple[int, bytes]:
        del url, verify
        timeouts.append(timeout)
        raise TimeoutError("temporary")

    crawler = JupiterCrawler(
        policy=FetchPolicy(timeout_seconds=10), fetcher=fetch, sleep=lambda _: None
    )
    with pytest.raises(CrawlError, match="fetch_error"):
        await crawler._fetch_with_retry("https://example.test")

    assert len(timeouts) == 4
    assert timeouts[0] == pytest.approx(2.5, abs=0.01)
    assert timeouts[-1] == pytest.approx(10, abs=0.01)
    assert timeouts == sorted(timeouts)


@pytest.mark.asyncio
async def test_unclassified_fetch_failure_aborts_publication() -> None:
    async def fetch(url: str, verify: bool, timeout: float) -> tuple[int, bytes]:
        raise OSError("offline")

    crawler = JupiterCrawler(fetcher=fetch)
    with pytest.raises(CrawlError, match="fetch_error"):
        await crawler.crawl()


def test_candidate_versions_are_reused_only_by_code_and_verdis() -> None:
    previous = {("MAC0001", "1"): {"name": "old"}}
    crawler = JupiterCrawler(previous_versions=previous)
    assert (
        crawler.should_fetch_discipline(CandidateDiscipline("MAC0001", "A", "1", ("45",))) is False
    )
    assert (
        crawler.should_fetch_discipline(CandidateDiscipline("MAC0001", "A", "2", ("45",))) is True
    )


@pytest.mark.asyncio
async def test_explicit_empty_curriculum_remains_public_and_classified_in_snapshot(
    tmp_path: Path,
) -> None:
    empty_curriculum = (FIXTURES / "curriculum_empty_3057_3000.html").read_text(
        encoding="utf-8"
    ).encode("iso-8859-1")

    async def fetch(url: str, verify: bool, timeout: float) -> tuple[int, bytes]:
        del verify, timeout
        if "jupColegiadoLista" in url:
            return 200, b'<a href="jupColegiadoMenu?codcg=3">Escola Politecnica</a>'
        if "jupDisciplinaLista" in url:
            return 200, b'<a href="obterTurma?sgldis=0300001&verdis=1">Trabalho</a>'
        if "obterTurma" in url:
            return 200, b"<table><tr><td>Codigo da Turma</td><td>2026201</td></tr></table>"
        if "jupCursoLista" in url:
            return 200, (
                b"<table><tr><td>Campus: Sao Paulo</td></tr><tr><td>"
                b'<a href="listarGradeCurricular?codcg=3&codcur=3057&codhab=3000&tipo=N">'
                b"3057 3000</a></td><td>Habilitacao: Engenharia de Petroleo</td>"
                b"<td>integral</td></tr></table>"
            )
        if "listarGradeCurricular" in url:
            return 200, empty_curriculum
        if "obterDisciplina" in url:
            return 200, b"<table><tr><td>Disciplina: 0300001 - Trabalho</td></tr></table>"
        raise AssertionError(f"unexpected URL: {url}")

    data = await JupiterCrawler(fetcher=fetch, sleep=lambda _: None).crawl()

    assert len(data.curricula) == 1
    assert data.curricula[0].name == "Habilitacao: Engenharia de Petroleo"
    assert data.curricula[0].period_code == "integral"
    assert data.curricula[0].items == ()
    assert data.metadata.state_counts["no_current_curriculum"] == 1

    snapshot = tmp_path / "snapshot.sqlite"
    build_snapshot(data, snapshot)
    with Repository(snapshot) as repository:
        stored = repository.get_curriculum("curriculum:3057:3000")
    assert stored is not None and stored["items"] == ()


@pytest.mark.asyncio
async def test_unrecognized_empty_curriculum_still_aborts_collection() -> None:
    async def fetch(url: str, verify: bool, timeout: float) -> tuple[int, bytes]:
        del url, verify, timeout
        return 200, b"<html><body>unexpected response</body></html>"

    candidate = CandidateCurriculum("3057", "3000", "Petróleo", "3")
    crawler = JupiterCrawler(fetcher=fetch, sleep=lambda _: None)

    with pytest.raises(CrawlError, match="parse_error: curriculum 3057:3000"):
        await crawler._fetch_curriculum(candidate)


@pytest.mark.asyncio
async def test_collection_aborts_when_no_current_curriculum_is_discovered() -> None:
    async def fetch(url: str, verify: bool, timeout: float) -> tuple[int, bytes]:
        del verify, timeout
        if "jupColegiadoLista" in url:
            return 200, b'<a href="jupColegiadoMenu?codcg=3">Escola Politecnica</a>'
        if "jupDisciplinaLista" in url:
            return 200, b'<a href="obterTurma?sgldis=0300001&verdis=1">Trabalho</a>'
        if "obterTurma" in url:
            return 200, b"<table><tr><td>Codigo da Turma</td><td>2026201</td></tr></table>"
        if "jupCursoLista" in url:
            return 200, b"<html><body>unexpected curriculum index</body></html>"
        raise AssertionError(f"unexpected URL: {url}")

    with pytest.raises(CrawlError, match="invalid_source: no curriculum candidates"):
        await JupiterCrawler(fetcher=fetch, sleep=lambda _: None).crawl()


@pytest.mark.asyncio
async def test_discipline_details_are_fetched_concurrently() -> None:
    active_details = 0
    max_active_details = 0

    async def fetch(url: str, verify: bool, timeout: float) -> tuple[int, bytes]:
        nonlocal active_details, max_active_details
        del verify, timeout
        if "jupColegiadoLista" in url:
            return 200, b'<a href="jupColegiadoMenu?codcg=3">Escola Politecnica</a>'
        if "jupDisciplinaLista" in url:
            return 200, (
                b'<a href="obterTurma?sgldis=0300001&verdis=1">Um</a>'
                b'<a href="obterTurma?sgldis=0300002&verdis=1">Dois</a>'
            )
        if "obterTurma" in url:
            return 200, b"<table><tr><td>Codigo da Turma</td><td>2026201</td></tr></table>"
        if "obterDisciplina" in url:
            active_details += 1
            max_active_details = max(max_active_details, active_details)
            await asyncio.sleep(0)
            active_details -= 1
            code = "0300001" if "0300001" in url else "0300002"
            return 200, f"<table><tr><td>Disciplina: {code}</td></tr></table>".encode()
        raise AssertionError(f"unexpected URL: {url}")

    crawler = JupiterCrawler(fetcher=fetch, sleep=lambda _: None, collect_curricula=False)
    data = await crawler.crawl()

    assert len(data.disciplines) == 2
    assert max_active_details == 2
