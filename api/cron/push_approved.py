from __future__ import annotations

# ruff: noqa: E402
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dabud_job_agent.config import get_settings
from dabud_job_agent.main import build_sheet_store
from dabud_job_agent.workflows.push_approved_to_snov import run_push_approved


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
    run = asyncio.run(run_push_approved(settings, sheet))
    return {"statusCode": 200, "body": f"ok:{run.approved_pushed_to_snov}"}
