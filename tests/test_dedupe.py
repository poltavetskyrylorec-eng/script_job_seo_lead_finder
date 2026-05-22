from __future__ import annotations

from datetime import UTC, datetime

from dabud_job_agent.models import JobPosting
from dabud_job_agent.utils.dedupe import dedupe_jobs


def test_job_dedupe_by_url_and_fallback() -> None:
    now = datetime.now(UTC)
    base = {
        "source": "seek",
        "search_query": "SEO specialist",
        "job_title": "SEO Manager",
        "job_url": "https://seek.com.au/job/1?tracking=true",
        "published_at": now,
        "company_name": "Acme",
        "company_domain": "acme.com",
        "company_website": "https://acme.com",
        "city": "Sydney",
        "state": "NSW",
        "country": "Australia",
        "salary_raw": "",
        "employment_type": "Full-time",
        "job_description_summary": "SEO and AI search",
        "run_id": "run-1",
    }
    j1 = JobPosting(**base)
    j2 = JobPosting(**{**base, "job_url": "https://seek.com.au/job/1"})
    j3 = JobPosting(**{**base, "job_url": "https://seek.com.au/job/2", "job_title": "SEO Manager"})
    unique = dedupe_jobs([j1, j2, j3])
    assert len(unique) == 1
