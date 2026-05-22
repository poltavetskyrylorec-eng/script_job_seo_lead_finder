from __future__ import annotations

from dabud_job_agent.models import JobPosting


def enrich_company(job: JobPosting) -> JobPosting:
    """
    MVP enrichment via deterministic heuristics.
    Can be extended with compliant web data providers.
    """
    text = f"{job.company_name} {job.job_description_summary}".lower()
    if "team of" in text:
        job.company_size_estimate = 20
    elif "startup" in text:
        job.company_size_estimate = 12
    elif not job.company_size_estimate:
        job.company_size_estimate = 10
    return job
