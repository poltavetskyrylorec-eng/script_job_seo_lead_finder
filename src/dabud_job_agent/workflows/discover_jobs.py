from __future__ import annotations

from collections import Counter
import logging
from datetime import UTC, datetime
from uuid import uuid4

from dabud_job_agent.agents.company_classifier import classify_company
from dabud_job_agent.agents.company_researcher import enrich_company
from dabud_job_agent.agents.job_normalizer import normalize_job
from dabud_job_agent.config import Settings
from dabud_job_agent.models import JobPosting, RunStats, Status
from dabud_job_agent.sources.browser_provider import BrowserSearchAdapter
from dabud_job_agent.sources.search_provider import SearchProviderAdapter
from dabud_job_agent.storage.google_sheets import GoogleSheetsStore
from dabud_job_agent.utils.dates import is_within_last_hours
from dabud_job_agent.utils.dedupe import (
    canonicalize_url,
    dedupe_jobs,
    job_id,
    merge_jobs_by_company_signal,
    normalize_domain,
    sha256_text,
)

LOGGER = logging.getLogger(__name__)

SEARCH_QUERIES = [
    "SEO specialist",
    "SEO manager",
    "SEO director",
    "SEO lead",
    "Head of SEO",
    "GEO specialist",
    "AEO specialist",
    "AI SEO specialist",
    "AI search optimization",
    "Generative engine optimization",
    "digital marketing SEO",
    "organic growth",
    "Content marketer SEO",
    "SEO content writer",
    "SEO copywriter",
    "Digital PR specialist",
    "Head of Growth",
    "Digital marketing manager SEO",
    "Organic growth manager",
    "Search marketing manager",
]


def _format_source_counts(prefix: str, counts: Counter[str]) -> str:
    if not counts:
        return f"{prefix}=none"
    packed = ",".join(f"{source}:{count}" for source, count in sorted(counts.items()))
    return f"{prefix}={packed}"


def _qualify(job: JobPosting, settings: Settings) -> tuple[bool, str]:
    if "australia" not in job.country.lower() and "australia" not in job.location_hint().lower():
        return False, "non_au_location"
    if not is_within_last_hours(job.published_at, settings.timezone, settings.run_lookback_hours):
        return False, "outside_time_window"
    if max(job.seo_intent_score, job.ai_search_intent_score) <= 0:
        return False, "low_intent_score"
    if (job.company_size_estimate or 0) < settings.min_company_size:
        return False, "small_company"
    if (
        settings.exclude_low_salary
        and job.salary_min_aud is not None
        and job.salary_min_aud < settings.min_salary_aud
    ):
        return False, "salary_below_threshold"
    return True, "qualified"


def _mark_low_salary(job: JobPosting, settings: Settings) -> None:
    if job.salary_min_aud is not None and job.salary_min_aud < settings.min_salary_aud:
        job.qualification_reason = "low_salary"


def _filter_existing_jobs(jobs: list[JobPosting], sheet_store: GoogleSheetsStore) -> list[JobPosting]:
    existing_rows = sheet_store.get_rows("leads")
    existing_urls = {
        canonicalize_url(str(row.get("job_url", "")))
        for row in existing_rows
        if str(row.get("job_url", "")).strip()
    }
    existing_fallback_keys = {
        "|".join(
            [
                normalize_domain(str(row.get("company_domain") or row.get("company_website") or "")),
                str(row.get("job_title", "")).lower().strip(),
                str(row.get("city", "")).lower().strip(),
                str(row.get("published_at", "")).split("T")[0].strip(),
            ]
        )
        for row in existing_rows
    }
    existing_company_signal_keys = {
        "|".join(
            [
                str(row.get("company_name", "")).lower().strip(),
                normalize_domain(str(row.get("company_domain") or row.get("company_website") or "")),
            ]
        )
        for row in existing_rows
        if (
            normalize_domain(str(row.get("company_domain") or row.get("company_website") or ""))
            or str(row.get("company_name", "")).lower().strip() not in {"", "unknown", "n/a", "none"}
        )
    }

    output: list[JobPosting] = []
    for job in jobs:
        url_key = canonicalize_url(job.job_url)
        fallback_key = "|".join(
            [
                normalize_domain(job.company_domain or job.company_website or job.company_name),
                job.job_title.lower().strip(),
                job.city.lower().strip(),
                job.published_at.date().isoformat(),
            ]
        )
        company_signal_key = "|".join(
            [
                job.company_name.lower().strip(),
                normalize_domain(job.company_domain or job.company_website or job.company_name),
            ]
        )
        is_unknown_company = job.company_name.lower().strip() in {"", "unknown", "n/a", "none"} and not normalize_domain(
            job.company_domain or job.company_website
        )
        if (
            url_key in existing_urls
            or fallback_key in existing_fallback_keys
            or (not is_unknown_company and company_signal_key in existing_company_signal_keys)
        ):
            continue
        output.append(job)
    return output


async def run_discover(
    settings: Settings, sheet_store: GoogleSheetsStore, run: RunStats | None = None
) -> RunStats:
    if run is None:
        run_id = str(uuid4())
        run = RunStats(run_id=run_id, started_at=datetime.now(UTC), status="running")
        sheet_store.append_run(run)
    else:
        run_id = run.run_id

    adapter = (
        BrowserSearchAdapter(settings)
        if settings.job_search_provider.lower().strip() == "browser"
        else SearchProviderAdapter(settings)
    )
    raw_jobs = []
    since = datetime.now(UTC)
    for query in SEARCH_QUERIES:
        fetched = await adapter.fetch_jobs(query=query, location="Australia", since=since)
        raw_jobs.extend(fetched)
        LOGGER.info(
            "Fetched raw jobs",
            extra={"run_id": run_id, "query": query, "count": len(fetched), "source": adapter.source_name},
        )
    run.jobs_found_raw = len(raw_jobs)
    raw_by_source = Counter(job.source for job in raw_jobs)

    normalized = [normalize_job(item, run_id=run_id) for item in raw_jobs]
    deduped = dedupe_jobs(normalized)
    deduped = merge_jobs_by_company_signal(deduped)
    deduped = _filter_existing_jobs(deduped, sheet_store)
    run.jobs_after_dedupe = len(deduped)
    deduped_by_source = Counter(job.source for job in deduped)

    qualified: list[JobPosting] = []
    for job in deduped:
        if not job.lead_id:
            stable_job_key = job_id(job.source, job.job_url)
            job.lead_id = sha256_text(f"{run_id}:{stable_job_key}")
        job = classify_company(enrich_company(job))
        ok, reason = _qualify(job, settings)
        if not ok:
            job.qualification_status = "failed"
            job.qualification_reason = reason
            continue
        job.qualification_status = "qualified"
        job.contact_status = Status.PENDING_CONTACTS
        job.sequence_status = Status.NEW
        _mark_low_salary(job, settings)
        qualified.append(job)
    run.jobs_qualified = len(qualified)
    qualified_by_source = Counter(job.source for job in qualified)

    sheet_store.append_leads(qualified)
    run.finished_at = datetime.now(UTC)
    run.status = "success"
    run.notes = "; ".join(
        [
            f"qualified={run.jobs_qualified}",
            _format_source_counts("raw_src", raw_by_source),
            _format_source_counts("dedupe_src", deduped_by_source),
            _format_source_counts("qualified_src", qualified_by_source),
        ]
    )
    sheet_store.update_run(run)
    return run
