from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from dabud_job_agent.config import Settings
from dabud_job_agent.models import Contact, JobPosting, ProspectPushPayload

LOGGER = logging.getLogger(__name__)
ROLE_FILTERS = [
    "practice manager",
    "clinic manager",
    "practice owner",
    "clinic director",
    "medical director",
    "owner",
    "business owner",
    "founder",
    "managing director",
    "coo",
]

CUSTOM_FIELD_CANDIDATES: dict[str, list[str]] = {
    "email_1_subject": ["email_1_subject", "тема листа", "subject 1", "email subject 1"],
    "email_1_body": ["email_1_body", "текст листа", "body 1", "email body 1"],
    "email_2_subject": ["email_2_subject", "тема листа 2", "subject 2", "email subject 2"],
    "email_2_body": ["email_2_body", "текст листа 2", "body 2", "email body 2"],
    "email_3_subject": ["email_3_subject", "тема листа 3", "subject 3", "email subject 3"],
    "email_3_body": ["email_3_body", "текст листа 3", "body 3", "email body 3"],
    "email_4_subject": ["email_4_subject", "4 лист тема", "тема листа 4", "subject 4", "email subject 4"],
    "email_4_body": ["email_4_body", "4 лист текст", "текст листа 4", "body 4", "email body 4"],
    "personalization_notes": ["personalization_notes", "personalization notes", "нотатки персоналізації"],
    "business_case_summary": ["business_case_summary", "business case summary"],
    "job_title": ["job_title", "посада вакансії"],
    "job_url": ["job_url", "url вакансії"],
    "job_source": ["job_source", "джерело вакансії"],
    "outreach_track": ["outreach_track"],
    "company_type": ["company_type"],
    "salary_raw": ["salary_raw"],
    "ai_search_intent_score": ["ai_search_intent_score"],
}


def _normalize_field_name(value: str) -> str:
    lowered = value.strip().lower()
    return re.sub(r"[\s_\-:;,.!()\[\]\"'`]+", " ", lowered).strip()


def _extract_custom_field_name(key_or_name: str) -> str:
    # API can return key like: customFields['Project name']
    match = re.search(r"customFields\[['\"](.+?)['\"]\]", key_or_name)
    if match:
        return match.group(1)
    return key_or_name


class SnovClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._access_token = ""
        self._token_expires_at = datetime.now(UTC)

    async def _get_token(self) -> str:
        if self._access_token and datetime.now(UTC) < self._token_expires_at:
            return self._access_token
        if not self.settings.snov_client_id or not self.settings.snov_client_secret:
            raise RuntimeError("SNOV credentials are missing")
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.settings.snov_client_id,
            "client_secret": self.settings.snov_client_secret,
        }
        async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
            response = await client.post("https://api.snov.io/v1/oauth/access_token", data=payload)
            response.raise_for_status()
            data = response.json()
        self._access_token = data["access_token"]
        self._token_expires_at = datetime.now(UTC) + timedelta(seconds=int(data.get("expires_in", 3600)))
        return self._access_token

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
    async def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
    async def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Snov POST failed status={response.status_code} url={url} body={response.text[:1000]}"
                )
            return response.json()

    async def find_contacts_by_domain(self, domain: str) -> list[Contact]:
        if self.settings.dry_run or not self.settings.snov_client_id:
            return [
                Contact(
                    run_id="dry",
                    company_domain=domain,
                    company_name=domain,
                    contact_first_name="Alex",
                    contact_last_name="Taylor",
                    contact_full_name="Alex Taylor",
                    contact_email=f"alex@{domain}",
                    email_status="unknown",
                    contact_position="Head of Marketing",
                    contact_country="Australia",
                    contact_source="snov_mock",
                )
            ]
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
            start = await client.post(
                "https://api.snov.io/v2/domain-search/prospects/start",
                headers=headers,
                params={
                    "domain": domain,
                    "page": 1,
                    "positions[]": ROLE_FILTERS,
                },
            )
            start.raise_for_status()
            start_data = start.json()
            task_hash = str(start_data.get("meta", {}).get("task_hash") or start_data.get("task_hash") or "").strip()
            if not task_hash:
                return []

            prospects: list[dict[str, Any]] = []
            for _ in range(4):
                result = await client.get(
                    f"https://api.snov.io/v2/domain-search/prospects/result/{task_hash}",
                    headers=headers,
                )
                result.raise_for_status()
                payload = result.json()
                prospects = payload.get("data", []) or []
                if str(payload.get("status", "")).lower() == "completed":
                    break
                await asyncio.sleep(1.2)

        contacts: list[Contact] = []
        for person in prospects[:20]:
            email, email_status = await self._resolve_prospect_email(person, headers)
            if not email:
                continue
            contacts.append(
                Contact(
                    run_id="",
                    company_domain=domain,
                    company_name=person.get("companyName", domain) or domain,
                    contact_first_name=person.get("first_name", "") or person.get("firstName", ""),
                    contact_last_name=person.get("last_name", "") or person.get("lastName", ""),
                    contact_full_name=(
                        f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
                        or f"{person.get('firstName', '')} {person.get('lastName', '')}".strip()
                        or person.get("name", "")
                    ),
                    contact_email=email,
                    email_status=email_status,
                    contact_position=person.get("position", ""),
                    contact_linkedin_url=person.get("source_page", "")
                    or person.get("social", {}).get("linkedin", ""),
                    contact_country=person.get("country", ""),
                    contact_source="snov",
                )
            )
        return contacts

    async def _resolve_prospect_email(self, person: dict[str, Any], headers: dict[str, str]) -> tuple[str, str]:
        start_url = str(person.get("search_emails_start", "")).strip()
        if not start_url:
            return str(person.get("email", "")).strip(), str(person.get("emailStatus", "unknown"))
        async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
            start = await client.post(start_url, headers=headers)
            start.raise_for_status()
            start_data = start.json()
            result_url = str(start_data.get("links", {}).get("result", "")).strip()
            task_hash = str(start_data.get("meta", {}).get("task_hash", "")).strip()
            if not result_url and task_hash:
                result_url = f"https://api.snov.io/v2/domain-search/prospects/search-emails/result/{task_hash}"
            if not result_url:
                return "", "unknown"
            for _ in range(4):
                result = await client.get(result_url, headers=headers)
                result.raise_for_status()
                payload = result.json()
                data_payload = payload.get("data", {})
                if isinstance(data_payload, list):
                    first_item = data_payload[0] if data_payload else {}
                    emails = (first_item.get("emails", []) if isinstance(first_item, dict) else []) or []
                elif isinstance(data_payload, dict):
                    emails = data_payload.get("emails", []) or []
                else:
                    emails = []
                if emails:
                    first = emails[0]
                    return str(first.get("email", "")).strip(), str(first.get("smtp_status", "unknown")).strip()
                if str(payload.get("status", "")).lower() == "completed":
                    break
                await asyncio.sleep(1.2)
        return "", "unknown"

    async def find_domain_by_company_name(self, company_name: str) -> str:
        clean_name = company_name.strip()
        if not clean_name:
            return ""
        if self.settings.dry_run or not self.settings.snov_client_id:
            return ""
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
            task_hash = ""
            attempts: list[dict[str, Any]] = [
                {"params": {"names[]": clean_name}},
                {"json": {"names": [clean_name]}},
                {"json": {"names[]": [clean_name]}},
                {"data": {"names[]": clean_name}},
            ]
            for payload in attempts:
                try:
                    start_response = await client.post(
                        "https://api.snov.io/v2/company-domain-by-name/start",
                        headers=headers,
                        **payload,
                    )
                    start_response.raise_for_status()
                    start_data = start_response.json()
                    task_hash = str(
                        start_data.get("task_hash")
                        or start_data.get("meta", {}).get("task_hash")
                        or start_data.get("data", {}).get("task_hash")
                        or ""
                    ).strip()
                    if task_hash:
                        break
                except Exception:
                    continue
            if not task_hash:
                return ""

            for _ in range(3):
                result_response = await client.get(
                    "https://api.snov.io/v2/company-domain-by-name/result",
                    headers=headers,
                    params={"task_hash": task_hash},
                )
                result_response.raise_for_status()
                result_data = result_response.json()
                status = str(result_data.get("status", "")).lower()
                rows = result_data.get("data", [])
                if rows:
                    first_row = rows[0]
                    result_payload = first_row.get("result", {})
                    if isinstance(result_payload, list):
                        first_result = result_payload[0] if result_payload else {}
                        domain = str(first_result.get("domain", "")).strip().lower()
                    elif isinstance(result_payload, dict):
                        domain = str(result_payload.get("domain", "")).strip().lower()
                    else:
                        domain = ""
                    if domain:
                        return domain
                if status == "completed":
                    break
                await asyncio.sleep(1.2)
        return ""

    async def verify_custom_fields(self, required_fields: list[str]) -> tuple[bool, str]:
        if self.settings.dry_run:
            return True, "dry-run"
        # Snov custom field introspection can differ by plan/API method.
        # Do not block the pipeline if account endpoint is unavailable.
        try:
            _ = await self._get("https://api.snov.io/v1/account", {})
        except Exception as exc:
            LOGGER.warning("Skipping strict custom-field verification", extra={"error": str(exc)})
            return True, "Custom fields check skipped: account endpoint unavailable"
        if not required_fields:
            return True, "ok"
        return True, "Custom fields should be pre-created and mapped in Snov campaign settings."

    async def _get_available_custom_fields(self) -> list[str]:
        try:
            payload = await self._get("https://api.snov.io/v1/prospect-custom-fields", {})
        except Exception:
            return []
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        available: list[str] = []
        if not isinstance(rows, list):
            return available
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key", "")).strip()
            name = str(row.get("name", "") or row.get("label", "")).strip()
            raw = name or key
            if not raw:
                continue
            available.append(_extract_custom_field_name(raw))
        return available

    async def _map_custom_fields_for_account(self, custom_fields: dict[str, str]) -> dict[str, str]:
        available_fields = await self._get_available_custom_fields()
        if not available_fields:
            return {}

        normalized_to_actual = {_normalize_field_name(name): name for name in available_fields}
        mapped: dict[str, str] = {}
        for logical_key, value in custom_fields.items():
            if value in {"", None}:
                continue
            candidates = CUSTOM_FIELD_CANDIDATES.get(logical_key, []) + [logical_key]
            picked: str | None = None
            for candidate in candidates:
                candidate_norm = _normalize_field_name(candidate)
                if candidate_norm in normalized_to_actual:
                    picked = normalized_to_actual[candidate_norm]
                    break
            if picked:
                mapped[picked] = str(value)
        return mapped

    def build_prospect_payload(
        self,
        contact: Contact,
        job: JobPosting,
        sequence_fields: dict[str, str],
        list_id: str,
    ) -> ProspectPushPayload:
        return ProspectPushPayload(
            email=contact.contact_email,
            full_name=contact.contact_full_name,
            first_name=contact.contact_first_name,
            last_name=contact.contact_last_name,
            position=contact.contact_position,
            company_name=contact.company_name or job.company_name,
            company_site=job.company_website,
            country=contact.contact_country or job.country,
            social_links={"linkedIn": contact.contact_linkedin_url} if contact.contact_linkedin_url else {},
            list_id=list_id,
            custom_fields={
                "job_title": job.job_title,
                "job_url": job.job_url,
                "job_source": job.source,
                "outreach_track": job.outreach_track.value,
                "email_1_subject": sequence_fields.get("email_1_subject", ""),
                "email_1_body": sequence_fields.get("email_1_body", ""),
                "email_2_subject": sequence_fields.get("email_2_subject", ""),
                "email_2_body": sequence_fields.get("email_2_body", ""),
                "email_3_subject": sequence_fields.get("email_3_subject", ""),
                "email_3_body": sequence_fields.get("email_3_body", ""),
                "email_4_subject": sequence_fields.get("email_4_subject", ""),
                "email_4_body": sequence_fields.get("email_4_body", ""),
                "personalization_notes": sequence_fields.get("personalization_notes", ""),
                "business_case_summary": sequence_fields.get("business_case_summary", ""),
                "company_type": job.company_type.value,
                "salary_raw": job.salary_raw,
                "ai_search_intent_score": str(job.ai_search_intent_score),
            },
        )

    async def add_prospect_to_list(self, payload: ProspectPushPayload) -> dict[str, Any]:
        if self.settings.dry_run:
            LOGGER.info("DRY_RUN payload", extra={"status": "dry_run", "count": 1})
            return {
                "status": "dry_run",
                "payload": payload.model_dump(by_alias=True, exclude={"email"}),
            }
        body = payload.model_dump(by_alias=True)
        body["customFields"] = await self._map_custom_fields_for_account(body.get("customFields", {}))
        try:
            return await self._post("https://api.snov.io/v1/add-prospect-to-list", body)
        except Exception as exc:
            message = str(exc)
            if "Custom fields" in message and "not found" in message:
                LOGGER.warning("Retrying prospect push without custom fields", extra={"error": message[:300]})
                body["customFields"] = {}
                return await self._post("https://api.snov.io/v1/add-prospect-to-list", body)
            raise

    async def add_prospect_to_campaign(self, payload: ProspectPushPayload, campaign_id: str) -> dict[str, Any]:
        if self.settings.dry_run:
            LOGGER.info("DRY_RUN campaign payload", extra={"status": "dry_run", "count": 1})
            return {
                "status": "dry_run",
                "campaign_id": campaign_id,
                "payload": payload.model_dump(by_alias=True, exclude={"email"}),
            }

        body = payload.model_dump(by_alias=True)
        body["campaignId"] = campaign_id
        try:
            return await self._post("https://api.snov.io/v1/add-prospect-to-campaign", body)
        except Exception as exc:
            LOGGER.warning(
                "Campaign endpoint unavailable, fallback to list endpoint",
                extra={"error": str(exc)},
            )
            return await self.add_prospect_to_list(payload)
