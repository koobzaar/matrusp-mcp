import pytest

from matrusp_mcp.crawler.crawler import CrawlError, FetchPolicy, JupiterCrawler
from matrusp_mcp.crawler.models import CandidateDiscipline


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
