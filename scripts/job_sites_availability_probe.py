"""
Probe job board accessibility: page load, blocks (captcha/login), visible job listings.

Usage:
  python scripts/job_sites_availability_probe.py
  python scripts/job_sites_availability_probe.py --query "SEO manager" --json-out reports/job_sites_probe.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote_plus

from dabud_job_agent.config import get_settings

BLOCK_PATTERNS = re.compile(
    r"(captcha|recaptcha|unusual traffic|verify you are human|access denied|"
    r"sign in to continue|log in to view|please enable javascript|"
    r"cloudflare|bot detection|are you a robot)",
    re.IGNORECASE,
)

# source, label, search URL template, CSS selectors that indicate job cards/links
PROBE_TARGETS: list[tuple[str, str, str, list[str]]] = [
    (
        "seek",
        "SEEK Australia",
        "https://www.seek.com.au/{query_slug}-jobs/in-All-Australia",
        ["a[href*='/job/']", "[data-automation='normalJob']"],
    ),
    (
        "indeed",
        "Indeed Australia",
        "https://au.indeed.com/jobs?q={query}&l={location}&fromage=7",
        ["a[href*='/viewjob']", "div.job_seen_beacon", ".jobsearch-ResultsList li"],
    ),
    (
        "jora",
        "Jora Australia",
        "https://au.jora.com/j?q={query}&l={location}&sp=search",
        ["a[href*='/job/']", "a[href*='j?id=']", "article"],
    ),
    (
        "glassdoor",
        "Glassdoor Australia",
        "https://www.glassdoor.com.au/Job/jobs.htm?sc.keyword={query}&locT=N&locId=1&locKeyword={location}",
        ["a[href*='/job-listing/']", "[data-test='job-listing']", "li.JobsList_jobListItem"],
    ),
    (
        "linkedin_jobs",
        "LinkedIn Jobs",
        "https://www.linkedin.com/jobs/search/?keywords={query}&location={location}",
        ["a[href*='/jobs/view/']", ".jobs-search__results-list li", "div.base-card"],
    ),
    (
        "google_jobs",
        "Google Jobs (search)",
        "https://www.google.com/search?q={query}+jobs+{location}&ibp=htl;jobs",
        ["a[href*='jobs/']", "div[data-ved]", ".g"],
    ),
    (
        "ziprecruiter",
        "ZipRecruiter Australia",
        "https://www.ziprecruiter.com.au/jobs-search?search={query}&location={location}",
        ["a[href*='/job/']", "article", "div[class*='job']"],
    ),
    (
        "jooble",
        "Jooble Australia",
        "https://au.jooble.org/jobs-{query_slug}/{location_slug}",
        ["a[href*='/job/']", "article", "div[data-test*='job']"],
    ),
]


@dataclass
class SiteProbeResult:
    source: str
    label: str
    url: str
    ok: bool
    page_loaded: bool
    http_status: int | None
    final_url: str
    page_title: str
    job_links_found: int
    job_cards_found: int
    blocked: bool
    block_hint: str
    error: str
    checked_at: str


def _slug(text: str) -> str:
    return text.lower().strip().replace(" ", "-")


def build_url(template: str, query: str, location: str) -> str:
    return template.format(
        query=quote_plus(query),
        location=quote_plus(location),
        query_slug=_slug(query),
        location_slug=_slug(location),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check AU job boards: load + visible listings.")
    parser.add_argument("--query", default="SEO specialist", help="Test search query.")
    parser.add_argument("--location", default="Australia", help="Test location.")
    parser.add_argument("--wait-ms", type=int, default=2500, help="Extra wait after domcontentloaded.")
    parser.add_argument("--timeout-ms", type=int, default=45000, help="Navigation timeout.")
    parser.add_argument(
        "--sources",
        default="",
        help="Comma-separated sources to test (default: all). e.g. seek,indeed,jora",
    )
    parser.add_argument("--json-out", default="", help="Optional path to save JSON report.")
    return parser.parse_args()


async def probe_site(
    page,
    *,
    source: str,
    label: str,
    url: str,
    selectors: list[str],
    wait_ms: int,
    timeout_ms: int,
) -> SiteProbeResult:
    checked_at = datetime.now(UTC).isoformat()
    result = SiteProbeResult(
        source=source,
        label=label,
        url=url,
        ok=False,
        page_loaded=False,
        http_status=None,
        final_url="",
        page_title="",
        job_links_found=0,
        job_cards_found=0,
        blocked=False,
        block_hint="",
        error="",
        checked_at=checked_at,
    )
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_timeout(wait_ms)
        result.page_loaded = True
        result.http_status = response.status if response else None
        result.final_url = page.url
        result.page_title = await page.title()

        body_text = (await page.inner_text("body"))[:8000]
        block_match = BLOCK_PATTERNS.search(body_text)
        if block_match:
            result.blocked = True
            result.block_hint = block_match.group(0)

        # Count unique job-like links across selectors
        link_hrefs: set[str] = set()
        card_count = 0
        for selector in selectors:
            try:
                elements = await page.query_selector_all(selector)
                card_count += len(elements)
                for el in elements:
                    href = await el.get_attribute("href")
                    if href and ("/job" in href or "/viewjob" in href or "/jobs/" in href):
                        link_hrefs.add(href.split("?")[0])
            except Exception:
                continue

        result.job_cards_found = card_count
        result.job_links_found = len(link_hrefs)

        # Heuristic: loaded + not blocked + some listings
        has_listings = result.job_links_found >= 1 or result.job_cards_found >= 3
        result.ok = (
            result.page_loaded
            and result.http_status in (None, 200)
            and not result.blocked
            and has_listings
        )
        if result.page_loaded and not result.blocked and not has_listings:
            result.error = "page_opened_but_no_job_listings_detected"
    except Exception as exc:
        result.error = str(exc)
    return result


async def run_probe(args: argparse.Namespace) -> list[SiteProbeResult]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        print("Playwright not installed. Run: pip install playwright && playwright install chromium")
        raise SystemExit(1) from exc

    settings = get_settings()
    allowed = {s.strip() for s in args.sources.split(",") if s.strip()} if args.sources else None

    targets = [
        (src, label, build_url(tpl, args.query, args.location), sels)
        for src, label, tpl, sels in PROBE_TARGETS
        if allowed is None or src in allowed
    ]
    if not targets:
        print("No targets matched --sources filter.")
        raise SystemExit(1)

    results: list[SiteProbeResult] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=settings.browser_user_agent,
            locale="en-AU",
            timezone_id="Australia/Sydney",
            viewport={"width": 1366, "height": 900},
        )
        page = await context.new_page()
        for source, label, url, selectors in targets:
            print(f"Checking {label} ...", flush=True)
            results.append(
                await probe_site(
                    page,
                    source=source,
                    label=label,
                    url=url,
                    selectors=selectors,
                    wait_ms=args.wait_ms,
                    timeout_ms=args.timeout_ms,
                )
            )
        await browser.close()
    return results


def print_report(results: list[SiteProbeResult]) -> None:
    ok_count = sum(1 for r in results if r.ok)
    print("\n=== Job sites availability report ===")
    print(f"checked={len(results)} ok={ok_count} failed={len(results) - ok_count}")
    print(f"{'SOURCE':<16} {'STATUS':<8} {'HTTP':<5} {'LINKS':<6} {'CARDS':<6} {'BLOCKED':<8} NOTE")
    print("-" * 95)
    for r in results:
        status = "OK" if r.ok else "FAIL"
        http = str(r.http_status or "-")
        blocked = "yes" if r.blocked else "no"
        note = r.error or r.block_hint or (r.page_title[:40] if r.page_title else "")
        print(
            f"{r.source:<16} {status:<8} {http:<5} {r.job_links_found:<6} {r.job_cards_found:<6} "
            f"{blocked:<8} {note}"
        )
        print(f"  url: {r.url}")
        if r.final_url and r.final_url != r.url:
            print(f"  final: {r.final_url}")
    print()


def main() -> None:
    args = parse_args()
    results = asyncio.run(run_probe(args))
    print_report(results)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "query": args.query,
            "location": args.location,
            "results": [asdict(r) for r in results],
        }
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"JSON saved: {out_path}")

    if not all(r.page_loaded for r in results):
        sys.exit(2)
    if not any(r.ok for r in results):
        sys.exit(3)


if __name__ == "__main__":
    main()
