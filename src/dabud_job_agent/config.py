from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "ci", "prod"] = Field(default="local", alias="APP_ENV")
    dry_run: bool = Field(default=True, alias="DRY_RUN")
    timezone: str = Field(default="Australia/Sydney", alias="TIMEZONE")
    run_lookback_hours: int = Field(default=24, alias="RUN_LOOKBACK_HOURS")
    min_company_size: int = Field(default=5, alias="MIN_COMPANY_SIZE")
    min_salary_aud: int = Field(default=50000, alias="MIN_SALARY_AUD")
    exclude_low_salary: bool = Field(default=False, alias="EXCLUDE_LOW_SALARY")

    claude_code_oauth_token: str = Field(default="", alias="CLAUDE_CODE_OAUTH_TOKEN")
    claude_model: str = Field(default="claude-sonnet-4-6", alias="CLAUDE_MODEL")

    snov_client_id: str = Field(default="", alias="SNOV_CLIENT_ID")
    snov_client_secret: str = Field(default="", alias="SNOV_CLIENT_SECRET")
    snov_platform_list_id: str = Field(default="", alias="SNOV_PLATFORM_LIST_ID")
    snov_partner_list_id: str = Field(default="", alias="SNOV_PARTNER_LIST_ID")
    snov_campaign_id: str = Field(default="", alias="SNOV_CAMPAIGN_ID")

    google_sheets_spreadsheet_id: str = Field(default="", alias="GOOGLE_SHEETS_SPREADSHEET_ID")
    google_service_account_json_base64: str = Field(
        default="", alias="GOOGLE_SERVICE_ACCOUNT_JSON_BASE64"
    )

    job_search_provider: str = Field(default="browser", alias="JOB_SEARCH_PROVIDER")
    job_search_provider_api_key: str = Field(default="", alias="JOB_SEARCH_PROVIDER_API_KEY")
    job_search_provider_url: str = Field(default="", alias="JOB_SEARCH_PROVIDER_URL")
    browser_user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        alias="BROWSER_USER_AGENT",
    )
    vercel_cron_secret: str = Field(default="", alias="VERCEL_CRON_SECRET")

    http_timeout_seconds: float = Field(default=20.0, alias="HTTP_TIMEOUT_SECONDS")
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    max_contacts_per_company: int = Field(default=2, alias="MAX_CONTACTS_PER_COMPANY")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
