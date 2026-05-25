from __future__ import annotations

import logging
from datetime import UTC, datetime

from dabud_job_agent.config import Settings
from dabud_job_agent.integrations.snov import SnovClient
from dabud_job_agent.models import CompanyType, Contact, JobPosting, OutreachTrack, RunStats, Status
from dabud_job_agent.storage.google_sheets import GoogleSheetsStore

LOGGER = logging.getLogger(__name__)

REQUIRED_CUSTOM_FIELDS = [
    "job_title",
    "job_url",
    "job_source",
    "outreach_track",
    "email_1_subject",
    "email_1_body",
    "email_2_subject",
    "email_2_body",
    "email_3_subject",
    "email_3_body",
    "email_4_subject",
    "email_4_body",
    "personalization_notes",
    "business_case_summary",
    "company_type",
    "salary_raw",
    "ai_search_intent_score",
]


def _apply_real_name(text: str, first_name: str) -> str:
    if not first_name:
        return text
    output = text
    for marker in ("[First Name]", "{{first_name}}", "{first_name}", "<FIRST_NAME>", "<first_name>"):
        output = output.replace(marker, first_name)
    return output.replace("Hi there,", f"Hi {first_name},").replace("Hi There,", f"Hi {first_name},")


def _safe_company_type(value: str) -> CompanyType:
    try:
        return CompanyType(value)
    except Exception:
        return CompanyType.UNKNOWN


def _safe_outreach_track(value: str) -> OutreachTrack:
    try:
        return OutreachTrack(value)
    except Exception:
        return OutreachTrack.PLATFORM


def _build_job_from_row(row: dict[str, str]) -> JobPosting:
    return JobPosting(
        run_id=str(row.get("run_id", "")),
        lead_id=str(row.get("lead_id", "")),
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
        company_type=_safe_company_type(str(row.get("company_type", CompanyType.UNKNOWN.value) or "")),
        outreach_track=_safe_outreach_track(str(row.get("outreach_track", OutreachTrack.PLATFORM.value) or "")),
        job_description_summary=str(row.get("job_description_summary", "")),
    )


def _build_contact_from_sequence_row(row: dict[str, str]) -> Contact:
    full_name = str(row.get("contact_full_name", ""))
    parts = full_name.split(" ")
    first = parts[0] if parts else ""
    last = " ".join(parts[1:]) if len(parts) > 1 else ""
    return Contact(
        run_id=str(row.get("run_id", "")),
        lead_id=str(row.get("lead_id", "")),
        company_domain=str(row.get("company_domain", "")),
        company_name=str(row.get("company_name", "")),
        contact_first_name=first,
        contact_last_name=last,
        contact_full_name=full_name,
        contact_email=str(row.get("contact_email", "")),
        email_status="unknown",
        contact_position="",
        contact_country="Australia",
    )


async def run_push_approved(
    settings: Settings, sheet_store: GoogleSheetsStore, run: RunStats | None = None
) -> RunStats:
    snov = SnovClient(settings)
    ok, reason = await snov.verify_custom_fields(REQUIRED_CUSTOM_FIELDS)
    if not ok:
        raise RuntimeError(reason)

    sequences = sheet_store.get_rows("sequences")
    leads_rows = sheet_store.get_rows("leads")
    leads_by_lead_id = {
        (str(row.get("run_id", "")).strip(), str(row.get("lead_id", "")).strip()): row
        for row in leads_rows
        if str(row.get("lead_id", "")).strip()
    }
    leads_by_key = {
        (str(row.get("run_id", "")), str(row.get("company_domain", "")), str(row.get("company_name", ""))): row
        for row in leads_rows
    }

    pushed = 0
    for seq in sequences:
        approval_value = str(seq.get("approved") or seq.get("approval_status") or "").strip().lower()
        if approval_value not in {"yes", "approved"}:
            continue
        if seq.get("send_status") not in {Status.NOT_SENT, Status.SNOV_ERROR, "", None}:
            continue
        if not seq.get("contact_email"):
            continue
        seq_lead_id = str(seq.get("lead_id", "")).strip()
        seq_run_id = str(seq.get("run_id", "")).strip()
        lead_row = leads_by_lead_id.get((seq_run_id, seq_lead_id)) if seq_lead_id else None
        if lead_row is None:
            key = (
                seq_run_id,
                str(seq.get("company_domain", "")),
                str(seq.get("company_name", "")),
            )
            lead_row = leads_by_key.get(key)
        if not lead_row:
            continue
        job = _build_job_from_row(lead_row)
        contact = _build_contact_from_sequence_row(seq)
        list_id = (
            settings.snov_partner_list_id
            if job.outreach_track == OutreachTrack.PARTNER
            else settings.snov_platform_list_id
        )
        payload = snov.build_prospect_payload(
            contact=contact,
            job=job,
            sequence_fields={
                "email_1_subject": str(seq.get("email_1_subject", "")),
                "email_1_body": _apply_real_name(str(seq.get("email_1_body", "")), contact.contact_first_name),
                "email_2_subject": str(seq.get("email_2_subject", "")),
                "email_2_body": _apply_real_name(str(seq.get("email_2_body", "")), contact.contact_first_name),
                "email_3_subject": str(seq.get("email_3_subject", "")),
                "email_3_body": _apply_real_name(str(seq.get("email_3_body", "")), contact.contact_first_name),
                "email_4_subject": str(seq.get("email_4_subject", "")),
                "email_4_body": _apply_real_name(str(seq.get("email_4_body", "")), contact.contact_first_name),
                "personalization_notes": str(seq.get("personalization_notes", "")),
                "business_case_summary": str(seq.get("business_case_summary", "")),
            },
            list_id=list_id,
        )
        try:
            # User flow: campaign is fed from list automatically, so list push is enough.
            response = await snov.add_prospect_to_list(payload)
            send_status = Status.DRY_RUN if settings.dry_run else Status.PUSHED_TO_SNOV
            sequence_filters = {
                "run_id": str(seq.get("run_id", "")),
                "contact_email": str(seq.get("contact_email", "")),
            }
            if seq_lead_id:
                sequence_filters["lead_id"] = seq_lead_id
            updated = sheet_store.update_rows_where(
                "sequences",
                sequence_filters,
                {
                    "send_status": send_status,
                    "sent_to_snov_at": datetime.now(UTC).isoformat(),
                    "snov_list_id": list_id,
                    "snov_campaign_id": settings.snov_campaign_id,
                    "snov_error": "",
                },
                limit=1,
            )
            if updated == 0:
                sheet_store.update_rows(
                    "sequences",
                    "contact_email",
                    str(seq.get("contact_email", "")),
                    {
                        "send_status": send_status,
                        "sent_to_snov_at": datetime.now(UTC).isoformat(),
                        "snov_list_id": list_id,
                        "snov_campaign_id": settings.snov_campaign_id,
                        "snov_error": "",
                    },
                    limit=1,
                )
            if response.get("id"):
                contact_filters = {
                    "run_id": str(seq.get("run_id", "")),
                    "contact_email": str(seq.get("contact_email", "")),
                }
                if seq_lead_id:
                    contact_filters["lead_id"] = seq_lead_id
                updated_contacts = sheet_store.update_rows_where(
                    "contacts",
                    contact_filters,
                    {"snov_prospect_id": str(response.get("id"))},
                    limit=1,
                )
                if updated_contacts == 0:
                    sheet_store.update_rows(
                        "contacts",
                        "contact_email",
                        str(seq.get("contact_email", "")),
                        {"snov_prospect_id": str(response.get("id"))},
                        limit=1,
                    )
            pushed += 1
        except Exception as exc:
            sequence_filters = {
                "run_id": str(seq.get("run_id", "")),
                "contact_email": str(seq.get("contact_email", "")),
            }
            if seq_lead_id:
                sequence_filters["lead_id"] = seq_lead_id
            updated = sheet_store.update_rows_where(
                "sequences",
                sequence_filters,
                {"send_status": Status.SNOV_ERROR, "snov_error": str(exc)},
                limit=1,
            )
            if updated == 0:
                sheet_store.update_rows(
                    "sequences",
                    "contact_email",
                    str(seq.get("contact_email", "")),
                    {"send_status": Status.SNOV_ERROR, "snov_error": str(exc)},
                    limit=1,
                )

    if run:
        run.approved_pushed_to_snov += pushed
        run.finished_at = datetime.now(UTC)
        sheet_store.update_run(run)
        return run

    return RunStats(
        run_id=f"standalone-push-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status="success",
        approved_pushed_to_snov=pushed,
    )
