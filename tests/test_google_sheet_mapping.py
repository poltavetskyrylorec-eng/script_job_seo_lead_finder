from __future__ import annotations

from dabud_job_agent.storage.google_sheets import LEADS_COLUMNS, GoogleSheetsStore


def test_model_to_row_respects_column_order() -> None:
    payload = {"run_id": "r1", "source": "seek", "job_title": "SEO Manager"}
    row = GoogleSheetsStore._model_to_row(payload, LEADS_COLUMNS)
    assert row[0] == "r1"
    assert row[2] == "seek"
    assert row[5] == "SEO Manager"
