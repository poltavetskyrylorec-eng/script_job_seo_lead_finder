from __future__ import annotations

# ruff: noqa: E402
import asyncio
import os
import sys
from pathlib import Path

# Ensure local package import when running on Vercel runtime.
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dabud_job_agent.config import get_settings
from dabud_job_agent.main import build_sheet_store
from dabud_job_agent.workflows.discover_jobs import run_discover
from dabud_job_agent.workflows.enrich_contacts import run_enrich_contacts
from dabud_job_agent.workflows.generate_sequences import run_generate_sequences


def _authorized(request) -> bool:
    expected = os.getenv("VERCEL_CRON_SECRET", "")
    if not expected:
        return True
    auth = request.headers.get("authorization", "")
    return auth == f"Bearer {expected}"


def handler(request):
    if not _authorized(request):
        return {"statusCode": 401, "body": "unauthorized"}

    settings = get_settings()
    sheet = build_sheet_store(settings)

    async def _run():
        run = await run_discover(settings, sheet)
        await run_enrich_contacts(settings, sheet, run=run)
        await run_generate_sequences(settings, sheet, run=run)
        return run.run_id

    run_id = asyncio.run(_run())
    return {"statusCode": 200, "body": f"ok:{run_id}"}
