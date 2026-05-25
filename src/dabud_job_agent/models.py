from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CompanyType(StrEnum):
    END_CLIENT = "end_client"
    SEO_OR_MARKETING_AGENCY = "seo_or_marketing_agency"
    RECRUITING_OR_HR_AGENCY = "recruiting_or_hr_agency"
    SOFTWARE_OR_SAAS = "software_or_saas"
    ECOMMERCE = "ecommerce"
    PROFESSIONAL_SERVICES = "professional_services"
    MEDIA_OR_PUBLISHER = "media_or_publisher"
    UNKNOWN = "unknown"


class OutreachTrack(StrEnum):
    PLATFORM = "platform"
    AGENCY_RESELLER = "agency_reseller"
    PARTNER = "partner"


class Status(StrEnum):
    NEW = "new"
    PENDING_RESEARCH = "pending_research"
    RESEARCH_DONE = "research_done"
    PENDING_CONTACTS = "pending_contacts"
    CONTACTS_DONE = "contacts_done"
    NO_CONTACT_FOUND = "no_contact_found"
    CONTACT_ERROR = "contact_error"
    PENDING_SEQUENCE = "pending_sequence"
    SEQUENCE_DONE = "sequence_done"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    NOT_SENT = "not_sent"
    DRY_RUN = "dry_run"
    PUSHED_TO_SNOV = "pushed_to_snov"
    SNOV_ERROR = "snov_error"
    FAILED = "failed"
    SKIPPED_INVALID_COMPANY = "skipped_invalid_company"


class RawJobPosting(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str
    job_title: str
    company_name: str
    job_url: str
    company_url: str | None = None
    location: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    salary_raw: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    employment_type: str | None = None
    published_at: datetime
    description_raw: str = ""
    search_query_used: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    job_detail_status: str = "partial"


class JobPosting(BaseModel):
    source: str
    job_board_source: str = ""
    search_query: str
    lead_id: str = ""
    job_title: str
    job_url: str
    published_at: datetime
    company_name: str
    company_domain: str = ""
    company_website: str = ""
    city: str = ""
    state: str = ""
    country: str = "Australia"
    salary_raw: str = ""
    salary_min_aud: float | None = None
    salary_max_aud: float | None = None
    employment_type: str = ""
    job_description_summary: str = ""
    seo_intent_score: float = 0
    ai_search_intent_score: float = 0
    mentions_geo: bool = False
    mentions_aeo: bool = False
    mentions_ai_search: bool = False
    company_size_estimate: int | None = None
    company_type: CompanyType = CompanyType.UNKNOWN
    outreach_track: OutreachTrack = OutreachTrack.PLATFORM
    geo_aeo_status: str = "NEUTRAL"
    competitor_tool_detected: bool = False
    competitor_tool_names: str = ""
    qualification_status: str = Status.PENDING_CONTACTS
    qualification_reason: str = ""
    contact_status: str = Status.PENDING_CONTACTS
    sequence_status: str = Status.NEW
    approval_status: str = "pending"
    send_status: str = Status.NOT_SENT
    error_message: str = ""
    run_id: str
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def location_hint(self) -> str:
        return " ".join([self.city, self.state, self.country]).strip()


class Contact(BaseModel):
    run_id: str
    lead_id: str = ""
    company_domain: str
    company_name: str
    contact_first_name: str = ""
    contact_last_name: str = ""
    contact_full_name: str = ""
    contact_email: str = ""
    email_status: str = "unknown"
    contact_position: str = ""
    contact_linkedin_url: str = ""
    contact_country: str = ""
    contact_source: str = "snov"
    contact_priority_score: int = 0
    selected_for_outreach: bool = False
    snov_prospect_id: str = ""


class EmailSequence(BaseModel):
    run_id: str
    lead_id: str = ""
    job_url: str = ""
    company_domain: str
    company_name: str
    contact_email: str
    contact_full_name: str
    outreach_track: OutreachTrack
    email_1_subject: str
    email_1_body: str
    email_2_subject: str
    email_2_body: str
    email_3_subject: str
    email_3_body: str
    email_4_subject: str
    email_4_body: str
    personalization_notes: str
    business_case_summary: str
    approval_status: str = "pending"
    approved_by: str = ""
    approved_at: str = ""
    send_status: str = Status.NOT_SENT
    sent_to_snov_at: str = ""
    snov_list_id: str = ""
    snov_error: str = ""


class RunStats(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str = "running"
    jobs_found_raw: int = 0
    jobs_after_dedupe: int = 0
    jobs_qualified: int = 0
    companies_enriched: int = 0
    contacts_found: int = 0
    sequences_generated: int = 0
    approved_pushed_to_snov: int = 0
    errors_count: int = 0
    claude_cost_usd: float = 0.0
    notes: str = ""


class ProspectPushPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str
    full_name: str = Field(alias="fullName")
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    position: str
    company_name: str = Field(alias="companyName")
    company_site: str = Field(alias="companySite")
    country: str
    social_links: dict[str, str] = Field(default_factory=dict, alias="socialLinks")
    update_contact: bool = Field(default=True, alias="updateContact")
    create_duplicates: bool = Field(default=False, alias="createDuplicates")
    list_id: str = Field(alias="listId")
    custom_fields: dict[str, Any] = Field(default_factory=dict, alias="customFields")


class HealthcheckResult(BaseModel):
    ok: bool
    claude_auth_mode: str
    checks: dict[str, str]
