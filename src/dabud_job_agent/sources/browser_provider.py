from __future__ import annotations

import logging
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from dabud_job_agent.config import Settings
from dabud_job_agent.models import RawJobPosting

LOGGER = logging.getLogger(__name__)

SITE_TARGETS = [
    ("linkedin_jobs", "linkedin.com/jobs"),
    ("indeed", "au.indeed.com"),
    ("indeed", "indeed.com"),
    ("glassdoor", "glassdoor.com.au"),
    ("google_jobs", "google.com"),
    ("ziprecruiter", "ziprecruiter.com"),
    ("seek", "seek.com.au"),
    ("jora", "au.jora.com"),
    ("wellfound", "wellfound.com"),
    ("remote_co", "remote.co"),
    ("weworkremotely", "weworkremotely.com"),
    ("builtin", "builtin.com"),
    ("simplyhired", "simplyhired.com"),
    ("reed", "reed.co.uk"),
    ("totaljobs", "totaljobs.com"),
    ("stepstone", "stepstone.de"),
    ("jooble", "jooble.org"),
]

AU_PRIORITY_SOURCES = {
    "linkedin_jobs",
    "indeed",
    "glassdoor",
    "google_jobs",
    "ziprecruiter",
    "seek",
    "jora",
    "jooble",
}


def _source_from_link(link: str) -> str:
    for source, domain in SITE_TARGETS:
        if domain in link:
            return source
    return "browser_search"


def _normalize_serp_link(link: str) -> str:
    # DuckDuckGo often wraps real URLs as /l/?uddg=<encoded>.
    if "duckduckgo.com/l/" not in link:
        return link
    parsed = urlparse(link)
    params = parse_qs(parsed.query)
    encoded = (params.get("uddg") or [""])[0]
    return unquote(encoded) if encoded else link


def _clean_company_name(value: str) -> str:
    cleaned = value.strip()
    return cleaned if cleaned else "Unknown"


def _clean_title(value: str, fallback: str) -> str:
    cleaned = value.strip()
    return cleaned if cleaned else fallback


def _first_text(card, selectors: list[str]) -> str:
    for selector in selectors:
        node = card.select_one(selector)
        if node:
            text = node.get_text(" ", strip=True)
            if text:
                return text
    return ""


def _first_company_url(card, selectors: list[str], base_url: str) -> str | None:
    for selector in selectors:
        node = card.select_one(selector)
        if not node:
            continue
        href = str(node.get("href", "")).strip()
        if not href:
            continue
        url = urljoin(base_url, href)
        # Skip obvious job ad links, keep company/profile-like links.
        if any(part in url for part in ["/job/", "/viewjob", "/rc/clk"]):
            continue
        return url
    return None


class BrowserSearchAdapter:
    source_name = "browser_search"
    enabled = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def fetch_jobs(self, query: str, location: str, since: datetime) -> list[RawJobPosting]:
        # Compliance-first note:
        # We only parse public pages and skip login walls.
        direct_jobs = await self._fetch_direct_boards(query, location)
        direct_deduped = self._dedupe_raw_jobs(direct_jobs)
        direct_sources = {job.source for job in direct_deduped}

        # Fallback should work per-board, not only when direct returns zero globally.
        core_sources = {"seek", "indeed", "jora"}
        missing_sources = {source for source in core_sources if source not in direct_sources}
        if not missing_sources:
            return direct_deduped

        fallback_jobs = await self._fetch_fallback_for_sources(query, location, missing_sources)
        merged = direct_deduped + fallback_jobs
        return self._dedupe_raw_jobs(merged)

    async def _fetch_fallback_for_sources(
        self, query: str, location: str, missing_sources: set[str]
    ) -> list[RawJobPosting]:
        if not missing_sources:
            return []
        try:
            jobs = await self._fetch_with_playwright(query, location, only_sources=missing_sources)
            if jobs:
                return jobs
        except Exception as exc:
            LOGGER.warning(
                "Playwright fallback unavailable, trying HTTP parser",
                extra={"error": str(exc), "missing_sources": ",".join(sorted(missing_sources))},
            )
        return await self._fetch_with_http(query, location, only_sources=missing_sources)

    async def _fetch_direct_boards(self, query: str, location: str) -> list[RawJobPosting]:
        try:
            from playwright.async_api import async_playwright  # type: ignore[import-not-found]
        except Exception as exc:
            LOGGER.warning("Playwright not available for direct board parsing", extra={"error": str(exc)})
            return []

        now = datetime.now(UTC)
        jobs: list[RawJobPosting] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self.settings.browser_user_agent,
                locale="en-AU",
                timezone_id="Australia/Sydney",
            )
            page = await context.new_page()
            board_fetchers = [
                self._fetch_seek_direct,
                self._fetch_indeed_direct,
                self._fetch_jora_direct,
            ]
            for fetcher in board_fetchers:
                try:
                    board_jobs = await fetcher(page=page, query=query, location=location, now=now)
                    jobs.extend(board_jobs)
                except Exception as exc:
                    LOGGER.warning("Direct board fetch failed", extra={"source": fetcher.__name__, "error": str(exc)})
            await browser.close()
        return jobs

    async def _fetch_seek_direct(self, page, query: str, location: str, now: datetime) -> list[RawJobPosting]:
        q_slug = query.lower().replace(" ", "-")
        url = f"https://www.seek.com.au/{q_slug}-jobs/in-All-Australia"
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[RawJobPosting] = []
        for card in soup.select("[data-automation='normalJob'], article")[:20]:
            link_node = card.select_one("a[href*='/job/']")
            title_node = card.select_one("a[href*='/job/'], h3, h2")
            if not link_node:
                continue
            href = str(link_node.get("href", "")).strip()
            job_url = urljoin("https://www.seek.com.au", href)
            title = _clean_title(title_node.get_text(" ", strip=True) if title_node else "", query)
            snippet = card.get_text(" ", strip=True)[:500]
            company_name = _first_text(
                card,
                [
                    "[data-automation='jobCompany']",
                    "a[data-automation='jobCompany']",
                    "span[data-automation='jobCompany']",
                    "a[href*='/companies/']",
                ],
            )
            company_url = _first_company_url(
                card,
                ["a[data-automation='jobCompany']", "a[href*='/companies/']"],
                "https://www.seek.com.au",
            )
            jobs.append(
                RawJobPosting(
                    source="seek",
                    job_title=title,
                    company_name=_clean_company_name(company_name),
                    job_url=job_url,
                    company_url=company_url,
                    location=location,
                    city="",
                    state="",
                    country="Australia",
                    salary_currency="AUD",
                    published_at=now,
                    description_raw=snippet,
                    search_query_used=query,
                    fetched_at=now,
                    job_detail_status="partial",
                )
            )
        return jobs

    async def _fetch_indeed_direct(self, page, query: str, location: str, now: datetime) -> list[RawJobPosting]:
        url = f"https://au.indeed.com/jobs?q={quote_plus(query)}&l={quote_plus(location)}&fromage=1"
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[RawJobPosting] = []
        for card in soup.select("div.job_seen_beacon, li, article")[:20]:
            link_node = card.select_one("a[href*='/viewjob'], a[href*='/rc/clk']")
            title_node = card.select_one("h2 a, h2, h3")
            if not link_node:
                continue
            href = str(link_node.get("href", "")).strip()
            job_url = urljoin("https://au.indeed.com", href)
            title = _clean_title(title_node.get_text(" ", strip=True) if title_node else "", query)
            snippet = card.get_text(" ", strip=True)[:500]
            company_name = _first_text(
                card,
                [
                    "span[data-testid='company-name']",
                    "[data-testid='company-name']",
                    "span.companyName",
                    "a[data-testid='company-name']",
                ],
            )
            company_url = _first_company_url(
                card,
                ["a[data-testid='company-name']", "a[href*='/cmp/']"],
                "https://au.indeed.com",
            )
            jobs.append(
                RawJobPosting(
                    source="indeed",
                    job_title=title,
                    company_name=_clean_company_name(company_name),
                    job_url=job_url,
                    company_url=company_url,
                    location=location,
                    city="",
                    state="",
                    country="Australia",
                    salary_currency="AUD",
                    published_at=now,
                    description_raw=snippet,
                    search_query_used=query,
                    fetched_at=now,
                    job_detail_status="partial",
                )
            )
        return jobs

    async def _fetch_jora_direct(self, page, query: str, location: str, now: datetime) -> list[RawJobPosting]:
        url = f"https://au.jora.com/j?q={quote_plus(query)}&l={quote_plus(location)}&sp=search"
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[RawJobPosting] = []
        for card in soup.select("article, div[class*='job'], li")[:20]:
            link_node = card.select_one("a[href*='/job/'], a[href*='j?id=']")
            title_node = card.select_one("h2 a, h2, h3")
            if not link_node:
                continue
            href = str(link_node.get("href", "")).strip()
            job_url = urljoin("https://au.jora.com", href)
            title = _clean_title(title_node.get_text(" ", strip=True) if title_node else "", query)
            snippet = card.get_text(" ", strip=True)[:500]
            company_name = _first_text(
                card,
                [
                    "[data-automation='jobCompany']",
                    "span[class*='company']",
                    "a[href*='/company/']",
                    "a[href*='company']",
                ],
            )
            company_url = _first_company_url(
                card,
                ["a[href*='/company/']", "a[href*='company']"],
                "https://au.jora.com",
            )
            jobs.append(
                RawJobPosting(
                    source="jora",
                    job_title=title,
                    company_name=_clean_company_name(company_name),
                    job_url=job_url,
                    company_url=company_url,
                    location=location,
                    city="",
                    state="",
                    country="Australia",
                    salary_currency="AUD",
                    published_at=now,
                    description_raw=snippet,
                    search_query_used=query,
                    fetched_at=now,
                    job_detail_status="partial",
                )
            )
        return jobs

    async def _fetch_with_http(
        self, query: str, location: str, only_sources: set[str] | None = None
    ) -> list[RawJobPosting]:
        active_sites = self._active_sites(location, only_sources=only_sources)
        headers = {"User-Agent": self.settings.browser_user_agent, "Accept-Language": "en-AU,en;q=0.9"}
        all_jobs: list[RawJobPosting] = []
        async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds, follow_redirects=True) as client:
            for _source, domain in active_sites:
                q = f"{query} {location} site:{domain}"
                url = f"https://duckduckgo.com/html/?q={quote_plus(q)}"
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                items = soup.select(".result")
                all_jobs.extend(self._parse_serp_items(items, query))
        return self._dedupe_raw_jobs(all_jobs)

    async def _fetch_with_playwright(
        self, query: str, location: str, only_sources: set[str] | None = None
    ) -> list[RawJobPosting]:
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]

        active_sites = self._active_sites(location, only_sources=only_sources)
        all_jobs: list[RawJobPosting] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self.settings.browser_user_agent,
                locale="en-AU",
                timezone_id="Australia/Sydney",
            )
            page = await context.new_page()
            for _source, domain in active_sites:
                q = f"{query} {location} site:{domain}"
                search_url = f"https://duckduckgo.com/?q={quote_plus(q)}"
                await page.goto(search_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(1200)
                html = await page.content()
                soup = BeautifulSoup(html, "html.parser")
                items = soup.select('[data-testid="result"], .result')
                all_jobs.extend(self._parse_serp_items(items, query))
            await browser.close()
        return self._dedupe_raw_jobs(all_jobs)

    @staticmethod
    def _parse_serp_items(items: list, query: str) -> list[RawJobPosting]:
        now = datetime.now(UTC)
        jobs: list[RawJobPosting] = []
        for item in items[:20]:
            link_node = item.select_one("a[href]")
            title_node = item.select_one("h2, h3")
            snippet_node = item.select_one(".snippet, [data-result='snippet'], .result__snippet")
            if not link_node:
                continue
            link = _normalize_serp_link(str(link_node.get("href", "")).strip())
            if not link:
                continue
            if not any(domain in link for _source, domain in SITE_TARGETS):
                continue
            title = _clean_title(title_node.get_text(" ", strip=True) if title_node else "", query)
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            jobs.append(
                RawJobPosting(
                    source=_source_from_link(link),
                    job_title=title,
                    company_name="Unknown",
                    job_url=link,
                    company_url=None,
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
                    description_raw=snippet,
                    search_query_used=query,
                    fetched_at=now,
                    job_detail_status="partial",
                )
            )
        return jobs

    @staticmethod
    def _dedupe_raw_jobs(jobs: list[RawJobPosting]) -> list[RawJobPosting]:
        seen: set[str] = set()
        output: list[RawJobPosting] = []
        for job in jobs:
            if job.job_url in seen:
                continue
            seen.add(job.job_url)
            output.append(job)
        return output

    @staticmethod
    def _active_sites(location: str, only_sources: set[str] | None = None) -> list[tuple[str, str]]:
        def pick_first_domain_per_source(candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
            picked: list[tuple[str, str]] = []
            seen_sources: set[str] = set()
            for source, domain in candidates:
                if source in seen_sources:
                    continue
                picked.append((source, domain))
                seen_sources.add(source)
            return picked

        if "australia" not in location.lower():
            sites = SITE_TARGETS
        else:
            sites = [item for item in SITE_TARGETS if item[0] in AU_PRIORITY_SOURCES]
        if only_sources:
            sites = [item for item in sites if item[0] in only_sources]
            sites = pick_first_domain_per_source(sites)
        return sites
