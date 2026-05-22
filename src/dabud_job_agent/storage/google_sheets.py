from __future__ import annotations

import base64
import json
import logging
from datetime import date, datetime
from typing import Any

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

from dabud_job_agent.models import Contact, EmailSequence, JobPosting, RunStats

LOGGER = logging.getLogger(__name__)

LEADS_COLUMNS = [
    "run_id",
    "discovered_at",
    "source",
    "job_board_source",
    "search_query",
    "job_title",
    "job_url",
    "published_at",
    "company_name",
    "company_domain",
    "company_website",
    "city",
    "state",
    "country",
    "salary_raw",
    "salary_min_aud",
    "salary_max_aud",
    "employment_type",
    "job_description_summary",
    "seo_intent_score",
    "ai_search_intent_score",
    "mentions_geo",
    "mentions_aeo",
    "mentions_ai_search",
    "company_size_estimate",
    "company_type",
    "outreach_track",
    "geo_aeo_status",
    "competitor_tool_detected",
    "competitor_tool_names",
    "qualification_status",
    "qualification_reason",
    "contact_status",
    "sequence_status",
    "approval_status",
    "send_status",
    "error_message",
]

CONTACTS_COLUMNS = [
    "contact_first_name",
    "contact_last_name",
    "contact_full_name",
    "contact_email",
    "email_status",
    "contact_position",
    "contact_linkedin_url",
    "contact_country",
    "contact_source",
    "contact_priority_score",
    "selected_for_outreach",
    "snov_prospect_id",
]

SEQUENCES_COLUMNS = [
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
    "approved_by",
    "approved_at",
    "sent_to_snov_at",
    "snov_list_id",
    "snov_error",
]

PIPELINE_COLUMNS = LEADS_COLUMNS + CONTACTS_COLUMNS + SEQUENCES_COLUMNS + [
    "approved",  # Manual cell: yes/no
    "snov_campaign_id",
]

RUNS_COLUMNS = [
    "run_id",
    "started_at",
    "finished_at",
    "status",
    "jobs_found_raw",
    "jobs_after_dedupe",
    "jobs_qualified",
    "companies_enriched",
    "contacts_found",
    "sequences_generated",
    "approved_pushed_to_snov",
    "errors_count",
    "claude_cost_usd",
    "notes",
]


class GoogleSheetsStore:
    def __init__(self, spreadsheet_id: str, service_account_json_base64: str) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.client = self._build_client(service_account_json_base64)
        self.sheet = self.client.open_by_key(spreadsheet_id)
        self._records_cache: dict[str, tuple[list[str], list[dict[str, Any]]]] = {}

    def _build_client(self, service_account_json_base64: str) -> gspread.Client:
        raw = base64.b64decode(service_account_json_base64).decode("utf-8")
        info = json.loads(raw)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)

    def ensure_tabs(self) -> None:
        for title, cols in (
            ("pipeline", PIPELINE_COLUMNS),
            ("runs", RUNS_COLUMNS),
        ):
            self._ensure_tab(title, cols)

    def _ensure_tab(self, title: str, columns: list[str]) -> None:
        try:
            ws = self.sheet.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self.sheet.add_worksheet(title=title, rows=1000, cols=max(len(columns), 26))
            ws.append_row(columns)
            return
        first_row = ws.row_values(1)
        if first_row != columns:
            ws.update("1:1", [columns])

    def append_leads(self, leads: list[JobPosting]) -> None:
        if not leads:
            return
        rows = [self._model_to_row(lead.model_dump(), PIPELINE_COLUMNS) for lead in leads]
        self.sheet.worksheet("pipeline").append_rows(rows, value_input_option="USER_ENTERED")
        self._invalidate_cache("pipeline")

    def append_contacts(self, contacts: list[Contact]) -> None:
        if not contacts:
            return
        ws = self.sheet.worksheet("pipeline")
        headers, rows = self._get_headers_and_records("pipeline")
        for contact in contacts:
            payload = contact.model_dump()
            match_idx = None
            for idx, row in enumerate(rows, start=2):
                if (
                    str(row.get("run_id", "")) == payload.get("run_id", "")
                    and str(row.get("company_domain", "")) == payload.get("company_domain", "")
                    and not str(row.get("contact_email", "")).strip()
                ):
                    match_idx = idx
                    break
            if match_idx is None:
                # If all lead rows for this company are already occupied with contacts,
                # clone the first matching lead row to preserve source/job metadata.
                template_row = next(
                    (
                        row
                        for row in rows
                        if str(row.get("run_id", "")) == payload.get("run_id", "")
                        and str(row.get("company_domain", "")) == payload.get("company_domain", "")
                    ),
                    None,
                )
                if template_row is None:
                    LOGGER.warning(
                        "Skipping contact append: no lead row for contact",
                        extra={"run_id": payload.get("run_id", ""), "company_domain": payload.get("company_domain", "")},
                    )
                    continue
                new_row = dict(template_row)
                for key in CONTACTS_COLUMNS:
                    new_row[key] = payload.get(key, "")
                ws.append_row(self._model_to_row(new_row, headers), value_input_option="USER_ENTERED")
                rows.append(new_row)
                continue
            for key in CONTACTS_COLUMNS:
                rows[match_idx - 2][key] = payload.get(key, "")
            end_cell = rowcol_to_a1(match_idx, len(headers))
            ws.update(f"A{match_idx}:{end_cell}", [self._model_to_row(rows[match_idx - 2], headers)])
        self._set_cached_records("pipeline", headers, rows)

    def append_sequences(self, sequences: list[EmailSequence]) -> None:
        if not sequences:
            return
        ws = self.sheet.worksheet("pipeline")
        headers, rows = self._get_headers_and_records("pipeline")
        for seq in sequences:
            payload = seq.model_dump()
            match_idx = None
            payload_job_url = str(payload.get("job_url", "")).strip()
            for idx, row in enumerate(rows, start=2):
                same_run = str(row.get("run_id", "")) == payload.get("run_id", "")
                same_email = str(row.get("contact_email", "")) == payload.get("contact_email", "")
                if not (same_run and same_email):
                    continue
                if payload_job_url and str(row.get("job_url", "")).strip() == payload_job_url:
                    match_idx = idx
                    break
                if (
                    str(row.get("company_domain", "")) == payload.get("company_domain", "")
                ):
                    match_idx = idx
                    break
            if match_idx is None:
                template_row = next(
                    (
                        row
                        for row in rows
                        if str(row.get("run_id", "")) == payload.get("run_id", "")
                        and str(row.get("company_domain", "")) == payload.get("company_domain", "")
                    ),
                    None,
                )
                if template_row is None:
                    LOGGER.warning(
                        "Skipping sequence append: no lead row for sequence",
                        extra={
                            "run_id": payload.get("run_id", ""),
                            "company_domain": payload.get("company_domain", ""),
                            "contact_email": payload.get("contact_email", ""),
                        },
                    )
                    continue
                new_row = dict(template_row)
                new_row["contact_email"] = payload.get("contact_email", new_row.get("contact_email", ""))
                new_row["contact_full_name"] = payload.get("contact_full_name", new_row.get("contact_full_name", ""))
                for key in (*SEQUENCES_COLUMNS, "approval_status", "send_status", "outreach_track"):
                    new_row[key] = payload.get(key, "")
                ws.append_row(self._model_to_row(new_row, headers), value_input_option="USER_ENTERED")
                rows.append(new_row)
                continue
            for key in (*SEQUENCES_COLUMNS, "approval_status", "send_status", "outreach_track"):
                rows[match_idx - 2][key] = payload.get(key, "")
            end_cell = rowcol_to_a1(match_idx, len(headers))
            ws.update(f"A{match_idx}:{end_cell}", [self._model_to_row(rows[match_idx - 2], headers)])
        self._set_cached_records("pipeline", headers, rows)

    def append_run(self, run_stats: RunStats) -> None:
        row = self._model_to_row(run_stats.model_dump(), RUNS_COLUMNS)
        self.sheet.worksheet("runs").append_row(row, value_input_option="USER_ENTERED")
        self._invalidate_cache("runs")

    def update_run(self, run_stats: RunStats) -> None:
        ws = self.sheet.worksheet("runs")
        headers, records = self._get_headers_and_records("runs")
        for idx, row in enumerate(records, start=2):
            if row.get("run_id") == run_stats.run_id:
                end_cell = rowcol_to_a1(idx, len(RUNS_COLUMNS))
                ws.update(f"A{idx}:{end_cell}", [self._model_to_row(run_stats.model_dump(), RUNS_COLUMNS)])
                records[idx - 2] = {
                    header: value
                    for header, value in zip(headers, self._model_to_row(run_stats.model_dump(), RUNS_COLUMNS), strict=False)
                }
                self._set_cached_records("runs", headers, records)
                return
        self.append_run(run_stats)

    def get_rows(self, tab: str, filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
        _, rows = self._get_headers_and_records(self._tab_alias(tab))
        if tab == "contacts":
            rows = [row for row in rows if str(row.get("contact_email", "")).strip()]
        elif tab == "sequences":
            rows = [row for row in rows if str(row.get("email_1_subject", "")).strip()]
        if not filters:
            return rows
        output: list[dict[str, Any]] = []
        for row in rows:
            if all(str(row.get(key, "")).strip() == value for key, value in filters.items()):
                output.append(row)
        return output

    def update_rows(
        self, tab: str, match_key: str, match_value: str, values: dict[str, Any], limit: int = 0
    ) -> int:
        ws_title = self._tab_alias(tab)
        ws = self.sheet.worksheet(ws_title)
        headers, records = self._get_headers_and_records(ws_title)
        updates = 0
        for idx, row in enumerate(records, start=2):
            if str(row.get(match_key, "")).strip() != match_value:
                continue
            for key, value in values.items():
                if key not in headers:
                    LOGGER.warning("Unknown column in update", extra={"error": key})
                    continue
                safe_value = value.value if hasattr(value, "value") else value
                if isinstance(safe_value, (datetime, date)):
                    safe_value = safe_value.isoformat()
                records[idx - 2][key] = safe_value
            end_cell = rowcol_to_a1(idx, len(headers))
            ws.update(f"A{idx}:{end_cell}", [self._model_to_row(records[idx - 2], headers)])
            updates += 1
            if limit and updates >= limit:
                break
        self._set_cached_records(ws_title, headers, records)
        return updates

    def _get_headers_and_records(self, ws_title: str) -> tuple[list[str], list[dict[str, Any]]]:
        cached = self._records_cache.get(ws_title)
        if cached is not None:
            return cached
        ws = self.sheet.worksheet(ws_title)
        headers = ws.row_values(1)
        records = ws.get_all_records()
        self._records_cache[ws_title] = (headers, records)
        return headers, records

    def _set_cached_records(self, ws_title: str, headers: list[str], rows: list[dict[str, Any]]) -> None:
        self._records_cache[ws_title] = (headers, rows)

    def _invalidate_cache(self, ws_title: str) -> None:
        self._records_cache.pop(ws_title, None)

    @staticmethod
    def _tab_alias(tab: str) -> str:
        if tab in {"leads", "contacts", "sequences"}:
            return "pipeline"
        return tab

    @staticmethod
    def _model_to_row(payload: dict[str, Any], columns: list[str]) -> list[Any]:
        row: list[Any] = []
        for col in columns:
            value = payload.get(col, "")
            if hasattr(value, "value"):
                value = value.value
            if isinstance(value, (datetime, date)):
                value = value.isoformat()
            row.append(value)
        return row
