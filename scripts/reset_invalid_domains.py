from __future__ import annotations

from gspread.utils import rowcol_to_a1

from dabud_job_agent.config import get_settings
from dabud_job_agent.storage.google_sheets import PIPELINE_COLUMNS, GoogleSheetsStore


def main() -> None:
    settings = get_settings()
    store = GoogleSheetsStore(
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
        service_account_json_base64=settings.google_service_account_json_base64,
    )
    ws = store.sheet.worksheet("pipeline")
    headers = ws.row_values(1)
    rows = ws.get_all_records()
    bad = 0
    for idx, row in enumerate(rows, start=2):
        if str(row.get("company_domain", "")).strip().lower() != "javascript:void(0)":
            continue
        row["company_domain"] = ""
        row["company_website"] = ""
        row["contact_status"] = "pending_contacts"
        row["sequence_status"] = "new"
        row["contact_first_name"] = ""
        row["contact_last_name"] = ""
        row["contact_full_name"] = ""
        row["contact_email"] = ""
        row["contact_position"] = ""
        row["contact_linkedin_url"] = ""
        row["contact_country"] = ""
        row["contact_source"] = ""
        row["contact_priority_score"] = ""
        row["selected_for_outreach"] = ""
        row["snov_prospect_id"] = ""
        row["email_1_subject"] = ""
        row["email_1_body"] = ""
        row["email_2_subject"] = ""
        row["email_2_body"] = ""
        row["email_3_subject"] = ""
        row["email_3_body"] = ""
        row["email_4_subject"] = ""
        row["email_4_body"] = ""
        row["personalization_notes"] = ""
        row["business_case_summary"] = ""
        row["approved"] = ""
        row["send_status"] = "not_sent"
        row["snov_campaign_id"] = ""
        end_cell = rowcol_to_a1(idx, len(headers))
        ws.update(f"A{idx}:{end_cell}", [[row.get(col, "") for col in headers]])
        bad += 1
    print(f"reset_rows={bad}")


if __name__ == "__main__":
    main()
