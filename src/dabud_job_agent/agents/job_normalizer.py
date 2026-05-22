from __future__ import annotations

from urllib.parse import urlparse

from dabud_job_agent.models import JobPosting, RawJobPosting
from dabud_job_agent.utils.text import (
    AI_SIGNAL_KEYWORDS,
    COMPETITOR_KEYWORDS,
    INTENT_KEYWORDS,
    detect_mentions,
    keyword_score,
    parse_salary_aud,
    summarize_text,
)

JOB_BOARD_HOST_MARKERS = (
    "seek.com",
    "indeed.com",
    "jora.com",
    "linkedin.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "jooble.org",
)


def normalize_job(raw: RawJobPosting, run_id: str) -> JobPosting:
    salary_min, salary_max = parse_salary_aud(raw.salary_raw)
    merged_text = f"{raw.job_title}\n{raw.description_raw}"
    domain = ""
    company_website = raw.company_url or ""
    if raw.company_url:
        parsed = urlparse(raw.company_url)
        domain = parsed.netloc.replace("www.", "").lower()
        if any(marker in domain for marker in JOB_BOARD_HOST_MARKERS):
            domain = ""
            company_website = ""
    return JobPosting(
        source=raw.source,
        job_board_source=raw.source,
        search_query=raw.search_query_used,
        job_title=raw.job_title.strip(),
        job_url=raw.job_url,
        published_at=raw.published_at,
        company_name=raw.company_name.strip(),
        company_domain=domain,
        company_website=company_website,
        city=raw.city or "",
        state=raw.state or "",
        country=raw.country or "Australia",
        salary_raw=raw.salary_raw or "",
        salary_min_aud=salary_min if salary_min is not None else raw.salary_min,
        salary_max_aud=salary_max if salary_max is not None else raw.salary_max,
        employment_type=raw.employment_type or "",
        job_description_summary=summarize_text(raw.description_raw, max_len=420),
        seo_intent_score=keyword_score(merged_text, INTENT_KEYWORDS),
        ai_search_intent_score=keyword_score(merged_text, AI_SIGNAL_KEYWORDS),
        mentions_geo=detect_mentions(merged_text, ["geo", "generative engine optimization"]),
        mentions_aeo=detect_mentions(merged_text, ["aeo", "answer engine optimization"]),
        mentions_ai_search=detect_mentions(merged_text, AI_SIGNAL_KEYWORDS),
        competitor_tool_detected=detect_mentions(merged_text, COMPETITOR_KEYWORDS),
        competitor_tool_names=",".join([x for x in COMPETITOR_KEYWORDS if x in merged_text.lower()]),
        run_id=run_id,
    )
