from __future__ import annotations

from dabud_job_agent.models import CompanyType, JobPosting, OutreachTrack


def classify_company(job: JobPosting) -> JobPosting:
    haystack = f"{job.company_name} {job.job_title} {job.job_description_summary}".lower()
    if any(word in haystack for word in ("agency", "marketing agency", "seo agency")):
        company_type = CompanyType.SEO_OR_MARKETING_AGENCY
        track = OutreachTrack.AGENCY_RESELLER
    elif any(word in haystack for word in ("recruit", "talent", "staffing", "hr")):
        company_type = CompanyType.RECRUITING_OR_HR_AGENCY
        track = OutreachTrack.PARTNER
    elif any(word in haystack for word in ("saas", "software", "platform")):
        company_type = CompanyType.SOFTWARE_OR_SAAS
        track = OutreachTrack.PLATFORM
    elif any(word in haystack for word in ("ecommerce", "shopify", "marketplace")):
        company_type = CompanyType.ECOMMERCE
        track = OutreachTrack.PLATFORM
    elif any(word in haystack for word in ("legal", "medical", "finance", "real estate", "travel")):
        company_type = CompanyType.PROFESSIONAL_SERVICES
        track = OutreachTrack.PLATFORM
    elif any(word in haystack for word in ("publisher", "media", "newsroom")):
        company_type = CompanyType.MEDIA_OR_PUBLISHER
        track = OutreachTrack.PLATFORM
    else:
        company_type = CompanyType.END_CLIENT if job.seo_intent_score > 0 else CompanyType.UNKNOWN
        track = OutreachTrack.PLATFORM

    job.company_type = company_type
    job.outreach_track = track
    if job.competitor_tool_detected:
        job.geo_aeo_status = "COMPETITOR"
    elif job.mentions_geo or job.mentions_aeo or job.mentions_ai_search:
        job.geo_aeo_status = "UPGRADE"
    elif job.seo_intent_score > 0:
        job.geo_aeo_status = "NEW_REVENUE"
    else:
        job.geo_aeo_status = "NEUTRAL"
    return job
