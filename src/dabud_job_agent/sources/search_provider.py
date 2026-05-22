from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote_plus

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from dabud_job_agent.config import Settings
from dabud_job_agent.models import RawJobPosting
from dabud_job_agent.utils.text import summarize_text

LOGGER = logging.getLogger(__name__)


def _source_from_link(link: str) -> str:
    if "seek.com.au" in link:
        return "seek"
    if "indeed" in link:
        return "indeed"
    if "jora" in link:
        return "jora"
    if "glassdoor" in link:
        return "glassdoor"
    return "search_provider"


class SearchProviderAdapter:
    """
    Compliance-first discovery adapter.
    It consumes legal search provider output instead of direct scraping job boards.
    """

    source_name = "search_provider"
    enabled = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def fetch_jobs(self, query: str, location: str, since: datetime) -> list[RawJobPosting]:
        provider = self.settings.job_search_provider.lower().strip()
        if provider == "mock":
            return self._mock_results(query)
        if provider == "serpapi":
            return await self._fetch_serpapi(query, location)
        LOGGER.warning("Unknown job provider, adapter returns empty list", extra={"source": provider})
        return []

    def _mock_results(self, query: str) -> list[RawJobPosting]:
        now = datetime.now(UTC)
        items = [
            RawJobPosting(
                source="seek",
                job_title=f"{query} Specialist",
                company_name="Acme Health AU",
                job_url=f"https://www.seek.com.au/job/mock-{quote_plus(query)}-1",
                company_url="https://acmehealth.example",
                location="Sydney NSW, Australia",
                city="Sydney",
                state="NSW",
                country="Australia",
                salary_raw="AUD 90,000 - 110,000 per year",
                salary_min=90000,
                salary_max=110000,
                salary_currency="AUD",
                employment_type="Full-time",
                published_at=now,
                description_raw=(
                    "Own SEO roadmap, scale organic growth, and improve AI search visibility "
                    "across ChatGPT and AI Overviews."
                ),
                search_query_used=query,
                fetched_at=now,
                job_detail_status="partial",
            )
        ]
        return items

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
    async def _fetch_serpapi(self, query: str, location: str) -> list[RawJobPosting]:
        if not self.settings.job_search_provider_api_key:
            LOGGER.warning("SERP provider configured without API key")
            return []
        params = {
            "engine": "google",
            "q": f"{query} {location}",
            "api_key": self.settings.job_search_provider_api_key,
            "num": 20,
        }
        async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
            response = await client.get("https://serpapi.com/search.json", params=params)
            response.raise_for_status()
            data = response.json()
        return self._parse_serpapi(data, query)

    def _parse_serpapi(self, payload: dict[str, Any], query: str) -> list[RawJobPosting]:
        results: list[RawJobPosting] = []
        now = datetime.now(UTC)
        allowed_hosts = ("seek.com.au", "au.indeed.com", "glassdoor.com.au", "au.jora.com")
        for item in payload.get("organic_results", []):
            link = item.get("link", "")
            if not any(host in link for host in allowed_hosts):
                continue
            title = item.get("title", "").strip() or query
            snippet = item.get("snippet", "")
            results.append(
                RawJobPosting(
                    source=_source_from_link(link),
                    job_title=title,
                    company_name=item.get("source", "Unknown"),
                    job_url=link,
                    location="Australia",
                    city="",
                    state="",
                    country="Australia",
                    salary_raw="",
                    salary_min=None,
                    salary_max=None,
                    salary_currency="AUD",
                    employment_type="",
                    published_at=now,
                    description_raw=summarize_text(snippet, max_len=500),
                    search_query_used=query,
                    fetched_at=now,
                    job_detail_status="partial",
                )
            )
        return results
