from __future__ import annotations

from datetime import UTC, datetime

from dabud_job_agent.config import Settings
from dabud_job_agent.integrations.snov import SnovClient
from dabud_job_agent.models import CompanyType, Contact, JobPosting, OutreachTrack


def test_snov_payload_has_required_fields() -> None:
    settings = Settings(
        GOOGLE_SHEETS_SPREADSHEET_ID="x",
        GOOGLE_SERVICE_ACCOUNT_JSON_BASE64="e30=",
        CLAUDE_CODE_OAUTH_TOKEN="token",
    )
    client = SnovClient(settings)
    contact = Contact(
        run_id="1",
        company_domain="acme.com",
        company_name="Acme",
        contact_first_name="Alex",
        contact_last_name="Taylor",
        contact_full_name="Alex Taylor",
        contact_email="alex@acme.com",
        email_status="valid",
        contact_position="Head of Marketing",
        contact_country="Australia",
    )
    job = JobPosting(
        run_id="1",
        source="seek",
        search_query="seo",
        job_title="SEO Manager",
        job_url="https://example.com/job",
        published_at=datetime.now(UTC),
        company_name="Acme",
        company_domain="acme.com",
        company_website="https://acme.com",
        city="Sydney",
        state="NSW",
        country="Australia",
        salary_raw="90k",
        employment_type="Full-time",
        job_description_summary="SEO and AI search",
        company_type=CompanyType.SOFTWARE_OR_SAAS,
        outreach_track=OutreachTrack.PLATFORM,
    )
    payload = client.build_prospect_payload(
        contact,
        job,
        {
            "email_1_subject": "Subject 1",
            "email_1_body": "Body 1",
            "email_2_subject": "Subject 2",
            "email_2_body": "Body 2",
            "email_3_subject": "Subject 3",
            "email_3_body": "Body 3",
            "personalization_notes": "notes",
            "business_case_summary": "summary",
        },
        "list-1",
    )
    assert payload.list_id == "list-1"
    assert payload.custom_fields["job_title"] == "SEO Manager"
    assert payload.custom_fields["email_3_body"] == "Body 3"
