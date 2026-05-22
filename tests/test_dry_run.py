from __future__ import annotations

import pytest

from dabud_job_agent.config import Settings
from dabud_job_agent.integrations.snov import SnovClient
from dabud_job_agent.models import ProspectPushPayload


@pytest.mark.asyncio
async def test_dry_run_prevents_real_snov_push() -> None:
    settings = Settings(
        DRY_RUN=True,
        GOOGLE_SHEETS_SPREADSHEET_ID="x",
        GOOGLE_SERVICE_ACCOUNT_JSON_BASE64="e30=",
        CLAUDE_CODE_OAUTH_TOKEN="token",
    )
    client = SnovClient(settings)
    payload = ProspectPushPayload(
        email="alex@example.com",
        full_name="Alex Example",
        first_name="Alex",
        last_name="Example",
        position="CMO",
        company_name="Acme",
        company_site="https://acme.com",
        country="Australia",
        list_id="list-1",
    )
    response = await client.add_prospect_to_list(payload)
    assert response["status"] == "dry_run"
