from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dabud_job_agent.utils.dates import is_within_last_hours
from dabud_job_agent.utils.text import parse_salary_aud


def test_salary_parser_annualizes_hourly() -> None:
    min_salary, max_salary = parse_salary_aud("AUD 50 - 70 per hour")
    assert min_salary == 50 * 38 * 52
    assert max_salary == 70 * 38 * 52


def test_date_filter_last_24_hours() -> None:
    now = datetime.now(UTC)
    assert is_within_last_hours(now - timedelta(hours=23), "Australia/Sydney", 24)
    assert not is_within_last_hours(now - timedelta(hours=25), "Australia/Sydney", 24)
