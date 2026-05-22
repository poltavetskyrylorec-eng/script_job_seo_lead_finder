from __future__ import annotations

from datetime import UTC, datetime

from dabud_job_agent.agents.company_classifier import classify_company
from dabud_job_agent.models import CompanyType, JobPosting, OutreachTrack


def _job(title: str, company: str, summary: str) -> JobPosting:
    return JobPosting(
        run_id="run",
        source="seek",
        search_query="seo",
        job_title=title,
        job_url="https://example.com/job",
        published_at=datetime.now(UTC),
        company_name=company,
        company_domain="example.com",
        company_website="https://example.com",
        city="Sydney",
        state="NSW",
        country="Australia",
        salary_raw="",
        employment_type="Full-time",
        job_description_summary=summary,
    )


def test_company_classification_hr_goes_partner_track() -> None:
    job = _job("Digital Marketing Recruiter", "Talent Staffing Group", "Recruitment for SEO roles")
    out = classify_company(job)
    assert out.company_type == CompanyType.RECRUITING_OR_HR_AGENCY
    assert out.outreach_track == OutreachTrack.PARTNER


def test_company_classification_seo_agency_goes_reseller_track() -> None:
    job = _job("Head of SEO", "Growth Agency AU", "Lead SEO team delivery")
    out = classify_company(job)
    assert out.company_type == CompanyType.SEO_OR_MARKETING_AGENCY
    assert out.outreach_track == OutreachTrack.AGENCY_RESELLER
