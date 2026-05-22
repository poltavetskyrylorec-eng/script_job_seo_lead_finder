from __future__ import annotations

import logging
from datetime import UTC, datetime

from dabud_job_agent.config import Settings
from dabud_job_agent.integrations.claude import ClaudeClient, ClaudeEmailGenerationError
from dabud_job_agent.models import CompanyType, Contact, JobPosting, OutreachTrack, RunStats, Status
from dabud_job_agent.storage.google_sheets import GoogleSheetsStore

LOGGER = logging.getLogger(__name__)
INVALID_COMPANY_VALUES = {"", "unknown", "n/a", "none", "-"}
SEQUENCE_FIELDS = (
    "email_1_subject",
    "email_1_body",
    "email_2_subject",
    "email_2_body",
    "email_3_subject",
    "email_3_body",
    "email_4_subject",
    "email_4_body",
)


def _is_invalid_company_name(value: str) -> bool:
    return value.strip().lower() in INVALID_COMPANY_VALUES


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _has_existing_sequence_content(row: dict[str, str]) -> bool:
    return any(str(row.get(field, "")).strip() for field in SEQUENCE_FIELDS)


def _has_contact_name(row: dict[str, str]) -> bool:
    return bool(str(row.get("contact_first_name", "")).strip() or str(row.get("contact_full_name", "")).strip())


def _job_from_lead_row(row: dict[str, str]) -> JobPosting:
    return JobPosting(
        run_id=str(row.get("run_id", "")),
        source=str(row.get("source", "")),
        search_query=str(row.get("search_query", "")),
        job_title=str(row.get("job_title", "")),
        job_url=str(row.get("job_url", "")),
        published_at=datetime.now(UTC),
        company_name=str(row.get("company_name", "")),
        company_domain=str(row.get("company_domain", "")),
        company_website=str(row.get("company_website", "")),
        city=str(row.get("city", "")),
        state=str(row.get("state", "")),
        country=str(row.get("country", "Australia")),
        salary_raw=str(row.get("salary_raw", "")),
        salary_min_aud=None,
        salary_max_aud=None,
        employment_type=str(row.get("employment_type", "")),
        job_description_summary=str(row.get("job_description_summary", "")),
        seo_intent_score=float(row.get("seo_intent_score", 0) or 0),
        ai_search_intent_score=float(row.get("ai_search_intent_score", 0) or 0),
        mentions_geo=str(row.get("mentions_geo", "")).lower() == "true",
        mentions_aeo=str(row.get("mentions_aeo", "")).lower() == "true",
        mentions_ai_search=str(row.get("mentions_ai_search", "")).lower() == "true",
        company_size_estimate=int(row.get("company_size_estimate", 0) or 0),
        company_type=CompanyType(str(row.get("company_type", CompanyType.UNKNOWN.value))),
        outreach_track=OutreachTrack(str(row.get("outreach_track", OutreachTrack.PLATFORM.value))),
        competitor_tool_detected=str(row.get("competitor_tool_detected", "")).lower() == "true",
        competitor_tool_names=str(row.get("competitor_tool_names", "")),
        qualification_status=str(row.get("qualification_status", "")),
        qualification_reason=str(row.get("qualification_reason", "")),
        contact_status=str(row.get("contact_status", "")),
        sequence_status=str(row.get("sequence_status", "")),
        approval_status=str(row.get("approval_status", "pending")),
        send_status=str(row.get("send_status", Status.NOT_SENT)),
        error_message=str(row.get("error_message", "")),
    )


def _contact_from_row(row: dict[str, str]) -> Contact:
    return Contact(
        run_id=str(row.get("run_id", "")),
        company_domain=str(row.get("company_domain", "")),
        company_name=str(row.get("company_name", "")),
        contact_first_name=str(row.get("contact_first_name", "")),
        contact_last_name=str(row.get("contact_last_name", "")),
        contact_full_name=str(row.get("contact_full_name", "")),
        contact_email=str(row.get("contact_email", "")),
        email_status=str(row.get("email_status", "unknown")),
        contact_position=str(row.get("contact_position", "")),
        contact_linkedin_url=str(row.get("contact_linkedin_url", "")),
        contact_country=str(row.get("contact_country", "")),
        contact_source=str(row.get("contact_source", "")),
        contact_priority_score=int(row.get("contact_priority_score", 0) or 0),
        selected_for_outreach=str(row.get("selected_for_outreach", "")).lower() == "true",
        snov_prospect_id=str(row.get("snov_prospect_id", "")),
    )


async def run_generate_sequences(
    settings: Settings, sheet_store: GoogleSheetsStore, run: RunStats | None = None
) -> RunStats:
    claude = ClaudeClient(settings)
    pending_leads = [
        row for row in sheet_store.get_rows("leads") if row.get("contact_status") == Status.PENDING_SEQUENCE
    ]
    if run:
        pending_leads = [row for row in pending_leads if str(row.get("run_id", "")) == run.run_id]
    generated = 0
    errors = 0
    generated_contact_keys: set[tuple[str, str]] = set()
    for lead in pending_leads:
        if _is_invalid_company_name(str(lead.get("company_name", ""))):
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
        job = _job_from_lead_row(lead)
        contacts_rows = sheet_store.get_rows("contacts", {"company_domain": job.company_domain, "run_id": job.run_id})
        contacts_rows = [
            row for row in contacts_rows if str(row.get("job_url", "")).strip() == job.job_url or not str(row.get("job_url", "")).strip()
        ]
        selected_rows = [row for row in contacts_rows if str(row.get("selected_for_outreach", "")).lower() == "true"]
        eligible_rows = []
        for row in selected_rows:
            if _has_existing_sequence_content(row):
                continue
            if not _normalize_email(str(row.get("contact_email", ""))):
                continue
            if not _has_contact_name(row):
                continue
            row_company_name = str(row.get("company_name", "")).strip() or job.company_name
            if _is_invalid_company_name(row_company_name):
                continue
            eligible_rows.append(row)
        contacts = [_contact_from_row(row) for row in eligible_rows]
        deduped_contacts: list[Contact] = []
        seen_contact_keys: set[str] = set()
        for contact in contacts:
            email_key = _normalize_email(contact.contact_email)
            if not email_key:
                continue
            if email_key in seen_contact_keys:
                continue
            seen_contact_keys.add(email_key)
            deduped_contacts.append(contact)
        contacts = deduped_contacts
        if not contacts:
            if selected_rows and any(_has_existing_sequence_content(row) for row in selected_rows):
                sheet_store.update_rows(
                    "leads",
                    "job_url",
                    job.job_url,
                    {
                        "sequence_status": Status.SEQUENCE_DONE,
                        "approval_status": "pending",
                        "send_status": Status.NOT_SENT,
                        "error_message": "",
                    },
                    limit=1,
                )
            continue
        sequences = []
        lead_errors: list[str] = []
        for contact in contacts:
            if not contact.contact_email:
                continue
            dedupe_key = (job.run_id, _normalize_email(contact.contact_email))
            if dedupe_key in generated_contact_keys:
                continue
            try:
                seq = await claude.generate_email_sequence(job, contact)
            except ClaudeEmailGenerationError as exc:
                errors += 1
                lead_errors.append(f"{contact.contact_email}: {exc}")
                LOGGER.error(
                    "Skipped sequence generation for contact",
                    extra={"contact_email": contact.contact_email, "error": str(exc)},
                )
                continue
            seq.approval_status = "pending"
            seq.send_status = Status.NOT_SENT
            sequences.append(seq)
            generated_contact_keys.add(dedupe_key)
        if sequences:
            sheet_store.append_sequences(sequences)
            generated += len(sequences)
            sheet_store.update_rows(
                "leads",
                "job_url",
                job.job_url,
                {
                    "sequence_status": Status.SEQUENCE_DONE,
                    "approval_status": "pending",
                    "send_status": Status.NOT_SENT,
                    "error_message": "",
                },
                limit=1,
            )
        elif lead_errors:
            sheet_store.update_rows(
                "leads",
                "job_url",
                job.job_url,
                {"error_message": " | ".join(lead_errors)[:500]},
                limit=1,
            )

    if run:
        run.sequences_generated += generated
        run.errors_count += errors
        run.claude_cost_usd += claude.estimated_cost_usd
        run.finished_at = datetime.now(UTC)
        sheet_store.update_run(run)
        return run
    return RunStats(
        run_id=f"standalone-generate-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status="success",
        sequences_generated=generated,
        errors_count=errors,
        claude_cost_usd=claude.estimated_cost_usd,
    )
