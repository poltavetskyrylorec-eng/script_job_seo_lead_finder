from __future__ import annotations

import hashlib
from urllib.parse import urlparse, urlunparse

from dabud_job_agent.models import Contact, JobPosting, OutreachTrack


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    clean = parsed._replace(query="", fragment="")
    return urlunparse(clean).rstrip("/")


def normalize_domain(domain_or_url: str) -> str:
    raw = domain_or_url.strip().lower()
    if raw in {"", "unknown", "n/a", "none", "-", "null"}:
        return ""
    parsed = urlparse(domain_or_url if "://" in domain_or_url else f"https://{domain_or_url}")
    domain = parsed.netloc.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def job_id(source: str, job_url: str) -> str:
    return sha256_text(f"{source}:{canonicalize_url(job_url)}")


def company_id(domain: str) -> str:
    return normalize_domain(domain)


def contact_id(email: str) -> str:
    return sha256_text(email.lower().strip())


def sequence_id(job_key: str, email: str, track: OutreachTrack) -> str:
    return sha256_text(f"{job_key}:{email.lower().strip()}:{track.value}")


def dedupe_jobs(jobs: list[JobPosting]) -> list[JobPosting]:
    seen_url: set[str] = set()
    seen_fallback: set[str] = set()
    unique: list[JobPosting] = []
    for job in jobs:
        url_key = canonicalize_url(job.job_url)
        company_name = job.company_name.lower().strip()
        company_domain = normalize_domain(job.company_domain or job.company_website)
        has_company_identity = bool(company_domain) or company_name not in {"", "unknown", "n/a", "none"}
        fallback = "|".join(
            [
                company_domain or normalize_domain(job.company_name),
                job.job_title.lower().strip(),
                job.city.lower().strip(),
                job.published_at.date().isoformat(),
            ]
        )
        if not has_company_identity:
            fallback = f"url::{url_key}"
        if url_key in seen_url or fallback in seen_fallback:
            continue
        seen_url.add(url_key)
        seen_fallback.add(fallback)
        unique.append(job)
    return unique


def dedupe_contacts(contacts: list[Contact]) -> list[Contact]:
    seen: set[str] = set()
    unique: list[Contact] = []
    for contact in contacts:
        key = contact.contact_email.lower().strip()
        if not key:
            key = f"{contact.company_domain}:{contact.contact_full_name.lower().strip()}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(contact)
    return unique


def merge_jobs_by_company_signal(jobs: list[JobPosting]) -> list[JobPosting]:
    """
    Keep one intent signal per company+domain and aggregate discovery metadata.
    This follows one-company-one-outreach logic for hiring intent campaigns.
    """
    grouped: dict[str, JobPosting] = {}
    for job in jobs:
        company_name = job.company_name.lower().strip()
        company_domain = normalize_domain(job.company_domain or job.company_website)
        has_strong_company_identity = bool(company_domain) or company_name not in {"", "unknown", "n/a", "none"}

        if not has_strong_company_identity:
            # Do not collapse unknown entities into one record.
            grouped[f"url::{canonicalize_url(job.job_url)}"] = job
            continue

        company_key = "|".join(
            [
                company_name,
                company_domain or normalize_domain(job.company_name),
            ]
        )
        existing = grouped.get(company_key)
        if existing is None:
            grouped[company_key] = job
            continue

        # Merge source and query history for auditability.
        sources = {value.strip() for value in f"{existing.source},{job.source}".split(",") if value.strip()}
        existing.source = ",".join(sorted(sources))
        board_sources = {
            value.strip()
            for value in f"{existing.job_board_source},{job.job_board_source}".split(",")
            if value.strip()
        }
        existing.job_board_source = ",".join(sorted(board_sources))
        queries = {
            value.strip() for value in f"{existing.search_query},{job.search_query}".split(",") if value.strip()
        }
        existing.search_query = ",".join(sorted(queries))

        # Keep richer description and stronger intent signal.
        if len(job.job_description_summary) > len(existing.job_description_summary):
            existing.job_description_summary = job.job_description_summary
            existing.job_title = job.job_title
            existing.job_url = job.job_url
        if job.published_at > existing.published_at:
            existing.published_at = job.published_at
        existing.seo_intent_score = max(existing.seo_intent_score, job.seo_intent_score)
        existing.ai_search_intent_score = max(existing.ai_search_intent_score, job.ai_search_intent_score)
        existing.mentions_geo = existing.mentions_geo or job.mentions_geo
        existing.mentions_aeo = existing.mentions_aeo or job.mentions_aeo
        existing.mentions_ai_search = existing.mentions_ai_search or job.mentions_ai_search
    return list(grouped.values())
