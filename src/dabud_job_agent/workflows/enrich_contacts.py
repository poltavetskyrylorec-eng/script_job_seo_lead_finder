from __future__ import annotations

import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

from dabud_job_agent.agents.contact_selector import select_top_contacts
from dabud_job_agent.config import Settings
from dabud_job_agent.integrations.claude import ClaudeClient
from dabud_job_agent.integrations.snov import SnovClient
from dabud_job_agent.models import CompanyType, Contact, RunStats, Status
from dabud_job_agent.storage.google_sheets import GoogleSheetsStore

LOGGER = logging.getLogger(__name__)
INVALID_COMPANY_VALUES = {"", "unknown", "n/a", "none", "-"}
JOB_BOARD_DOMAINS = {
    "seek.com.au",
    "au.seek.com",
    "indeed.com",
    "au.indeed.com",
    "jora.com",
    "au.jora.com",
    "linkedin.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "jooble.org",
}


def _safe_company_type(value: str) -> CompanyType:
    try:
        return CompanyType(value)
    except Exception:
        return CompanyType.UNKNOWN


def _contacts_from_rows(rows: list[dict[str, str]]) -> list[Contact]:
    contacts: list[Contact] = []
    for row in rows:
        contacts.append(
            Contact(
                run_id=str(row.get("run_id", "")),
                company_domain=str(row.get("company_domain", "")),
                company_name=str(row.get("company_name", "")),
                contact_first_name=str(row.get("contact_first_name", "")),
                contact_last_name=str(row.get("contact_last_name", "")),
                contact_full_name=str(row.get("contact_full_name", "")),
                contact_email=str(row.get("contact_email", "")),
                email_status=str(row.get("email_status", "")) or "unknown",
                contact_position=str(row.get("contact_position", "")),
                contact_linkedin_url=str(row.get("contact_linkedin_url", "")),
                contact_country=str(row.get("contact_country", "")),
                contact_source=str(row.get("contact_source", "")) or "snov",
                contact_priority_score=int(row.get("contact_priority_score", 0) or 0),
                selected_for_outreach=str(row.get("selected_for_outreach", "")).lower() == "true",
                snov_prospect_id=str(row.get("snov_prospect_id", "")),
            )
        )
    return contacts


def _extract_domain(url_or_domain: str) -> str:
    if not url_or_domain:
        return ""
    lowered = url_or_domain.strip().lower()
    if lowered.startswith(("javascript:", "mailto:", "#")):
        return ""
    parsed = urlparse(url_or_domain if "://" in url_or_domain else f"https://{url_or_domain}")
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return ""
    domain = parsed.netloc.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _is_usable_domain(domain: str) -> bool:
    if not domain:
        return False
    if "." not in domain:
        return False
    lowered = domain.lower().strip()
    if lowered in {"javascript:void(0)", "unknown", "n/a"}:
        return False
    if any(blocked in lowered for blocked in JOB_BOARD_DOMAINS):
        return False
    return True


def _is_invalid_company_name(value: str) -> bool:
    return value.strip().lower() in INVALID_COMPANY_VALUES


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _dedupe_contacts(contacts: list[Contact]) -> list[Contact]:
    unique: list[Contact] = []
    seen: set[tuple[str, str, str]] = set()
    for contact in contacts:
        key = (
            str(contact.run_id).strip(),
            str(contact.company_domain).strip().lower(),
            _normalize_email(contact.contact_email),
        )
        if not key[2]:
            # Keep non-email contacts for debugging visibility, but avoid exact duplicates.
            key = (
                str(contact.run_id).strip(),
                str(contact.company_domain).strip().lower(),
                str(contact.contact_linkedin_url).strip().lower()
                or str(contact.contact_full_name).strip().lower(),
            )
        if key in seen:
            continue
        seen.add(key)
        unique.append(contact)
    return unique


async def run_enrich_contacts(
    settings: Settings, sheet_store: GoogleSheetsStore, run: RunStats | None = None
) -> RunStats:
    snov = SnovClient(settings)
    claude = ClaudeClient(settings)
    pending_statuses = {Status.PENDING_CONTACTS, "contact_retry", Status.CONTACT_ERROR}
    if not settings.dry_run:
        # Allow re-enrichment of rows that were previously filled by dry-run mock contacts.
        pending_statuses.add(Status.PENDING_SEQUENCE)
    leads = sheet_store.get_rows("leads")
    pending = [
        row
        for row in leads
        if row.get("contact_status") in pending_statuses
    ]
    if run:
        pending = [row for row in pending if str(row.get("run_id", "")) == run.run_id]
    seen_contact_emails_by_run: dict[str, set[str]] = {}
    processed = 0
    total_contacts = 0
    for lead in pending:
        lead_run_id = str(lead.get("run_id", "")).strip()
        if lead_run_id not in seen_contact_emails_by_run:
            existing_for_run = sheet_store.get_rows("contacts", {"run_id": lead_run_id})
            seen_contact_emails_by_run[lead_run_id] = {
                _normalize_email(str(row.get("contact_email", "")))
                for row in existing_for_run
                if _normalize_email(str(row.get("contact_email", "")))
            }
        company_name = str(lead.get("company_name", ""))
        if _is_invalid_company_name(company_name):
            sheet_store.update_rows(
                "leads",
                "job_url",
                str(lead.get("job_url", "")),
                {
                    "contact_status": Status.SKIPPED_INVALID_COMPANY,
                    "sequence_status": Status.NEW,
                    "error_message": "invalid_company_name",
                },
                limit=1,
            )
            continue
        domain = _extract_domain(str(lead.get("company_domain") or ""))
        website = str(lead.get("company_website") or "").strip()
        if not domain:
            domain = _extract_domain(website)
        if not domain:
            claude_domain, claude_website = await claude.find_company_domain(
                str(lead.get("company_name", "")),
                country_hint=str(lead.get("country", "Australia")) or "Australia",
            )
            if _is_usable_domain(claude_domain):
                domain = claude_domain
                if not website and claude_website:
                    website = claude_website
            else:
                # User requested fallback to Snov when Claude cannot resolve domain.
                snov_domain = await snov.find_domain_by_company_name(str(lead.get("company_name", "")))
                if _is_usable_domain(snov_domain):
                    domain = snov_domain
                    if not website:
                        website = f"https://{snov_domain}"
            if domain:
                sheet_store.update_rows(
                    "leads",
                    "job_url",
                    str(lead.get("job_url", "")),
                    {
                        "company_domain": domain,
                        "company_website": website,
                    },
                    limit=1,
                )
        if not domain:
            sheet_store.update_rows(
                "leads",
                "job_url",
                str(lead.get("job_url", "")),
                {"contact_status": Status.NO_CONTACT_FOUND, "error_message": "missing_company_domain_after_claude_snov"},
                limit=1,
            )
            continue

        try:
            contacts = await snov.find_contacts_by_domain(domain)
            typed_contacts: list[Contact] = []
            for contact in contacts:
                contact.run_id = str(lead.get("run_id", contact.run_id))
                contact.company_name = str(lead.get("company_name", contact.company_name))
                contact.company_domain = domain
                typed_contacts.append(contact)

            existing_rows = sheet_store.get_rows(
                "contacts",
                {"company_domain": domain, "run_id": str(lead.get("run_id", ""))},
            )
            if not settings.dry_run:
                existing_rows = [row for row in existing_rows if str(row.get("contact_source", "")) != "snov_mock"]
            existing = _contacts_from_rows(existing_rows)
            selected = select_top_contacts(
                contacts=typed_contacts + existing,
                company_type=_safe_company_type(str(lead.get("company_type", CompanyType.UNKNOWN.value))),
                max_count=settings.max_contacts_per_company,
            )
            selected = _dedupe_contacts(selected)
            selected = [
                contact
                for contact in selected
                if not _normalize_email(contact.contact_email)
                or _normalize_email(contact.contact_email) not in seen_contact_emails_by_run[lead_run_id]
            ]
            sheet_store.append_contacts(selected)
            for contact in selected:
                email = _normalize_email(contact.contact_email)
                if email:
                    seen_contact_emails_by_run[lead_run_id].add(email)
            total_contacts += len(selected)
            status = Status.PENDING_SEQUENCE if selected else Status.NO_CONTACT_FOUND
            sheet_store.update_rows(
                "leads",
                "job_url",
                str(lead.get("job_url", "")),
                {"contact_status": status, "sequence_status": Status.PENDING_SEQUENCE if selected else Status.NEW},
                limit=1,
            )
        except Exception as exc:
            LOGGER.error("Contact enrichment failed", extra={"error": str(exc), "source": "snov"})
            sheet_store.update_rows(
                "leads",
                "job_url",
                str(lead.get("job_url", "")),
                {"contact_status": Status.CONTACT_ERROR, "error_message": str(exc)},
                limit=1,
            )
        processed += 1

    if run:
        run.contacts_found += total_contacts
        run.companies_enriched += processed
        run.claude_cost_usd += claude.estimated_cost_usd
        run.finished_at = datetime.now(UTC)
        sheet_store.update_run(run)
        return run
    return RunStats(
        run_id=f"standalone-enrich-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status="success",
        contacts_found=total_contacts,
        companies_enriched=processed,
        claude_cost_usd=claude.estimated_cost_usd,
    )
