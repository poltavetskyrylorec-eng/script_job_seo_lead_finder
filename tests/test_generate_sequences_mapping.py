from __future__ import annotations

from dabud_job_agent.models import CompanyType, OutreachTrack
from dabud_job_agent.workflows.generate_sequences import _job_from_lead_row


def test_job_from_lead_row_uses_safe_enum_fallbacks() -> None:
    row = {
        "run_id": "run-1",
        "lead_id": "lead-1",
        "source": "seek",
        "search_query": "seo",
        "job_title": "SEO Manager",
        "job_url": "https://example.com/job/1",
        "company_name": "Acme",
        "company_type": "invalid-value",
        "outreach_track": "bad-track",
    }
    job = _job_from_lead_row(row)
    assert job.lead_id == "lead-1"
    assert job.company_type == CompanyType.UNKNOWN
    assert job.outreach_track == OutreachTrack.PLATFORM

