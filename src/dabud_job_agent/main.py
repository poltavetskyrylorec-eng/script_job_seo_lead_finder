from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime

from dabud_job_agent.config import Settings, get_settings
from dabud_job_agent.integrations.claude import ClaudeClient
from dabud_job_agent.logging_config import configure_logging
from dabud_job_agent.models import HealthcheckResult, RunStats
from dabud_job_agent.storage.google_sheets import GoogleSheetsStore
from dabud_job_agent.workflows.discover_jobs import run_discover
from dabud_job_agent.workflows.enrich_contacts import run_enrich_contacts
from dabud_job_agent.workflows.generate_sequences import run_generate_sequences
from dabud_job_agent.workflows.push_approved_to_snov import run_push_approved

LOGGER = logging.getLogger(__name__)


def build_sheet_store(settings: Settings) -> GoogleSheetsStore:
    if not settings.google_sheets_spreadsheet_id:
        raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID is required")
    if not settings.google_service_account_json_base64:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON_BASE64 is required")
    store = GoogleSheetsStore(
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
        service_account_json_base64=settings.google_service_account_json_base64,
    )
    store.ensure_tabs()
    return store


def run_healthcheck(settings: Settings) -> HealthcheckResult:
    mode = ClaudeClient(settings).detect_auth_mode()
    checks = {
        "google_sheets_id": "ok" if settings.google_sheets_spreadsheet_id else "missing",
        "google_service_account": "ok" if settings.google_service_account_json_base64 else "missing",
        "snov_client_id": "ok" if settings.snov_client_id else "missing",
        "snov_client_secret": "ok" if settings.snov_client_secret else "missing",
        "claude_auth": mode,
        "dry_run": str(settings.dry_run).lower(),
    }
    ok = checks["google_sheets_id"] == "ok" and checks["google_service_account"] == "ok"
    if mode == "missing":
        ok = False
    return HealthcheckResult(ok=ok, claude_auth_mode=mode, checks=checks)


async def _run_command(args: argparse.Namespace) -> int:
    configure_logging()
    settings = get_settings()
    if args.command == "healthcheck":
        result = run_healthcheck(settings)
        LOGGER.info("Healthcheck", extra={"status": "ok" if result.ok else "failed"})
        print(result.model_dump_json(indent=2))
        if not result.ok:
            print("Healthcheck failed. Configure required env vars before production runs.")
            return 1
        return 0

    sheet_store = build_sheet_store(settings)
    if args.command == "discover":
        await run_discover(settings, sheet_store)
        return 0
    if args.command == "enrich-contacts":
        run = await run_enrich_contacts(settings, sheet_store)
        sheet_store.append_run(run)
        return 0
    if args.command == "generate-sequences":
        run = await run_generate_sequences(settings, sheet_store)
        sheet_store.append_run(run)
        return 0
    if args.command == "push-approved":
        run = await run_push_approved(settings, sheet_store)
        sheet_store.append_run(run)
        return 0
    if args.command == "run-all":
        run = RunStats(run_id=f"run-all-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}", started_at=datetime.now(UTC))
        sheet_store.append_run(run)
        run = await run_discover(settings, sheet_store)
        run = await run_enrich_contacts(settings, sheet_store, run=run)
        run = await run_generate_sequences(settings, sheet_store, run=run)
        if args.push_approved:
            run = await run_push_approved(settings, sheet_store, run=run)
        run.finished_at = datetime.now(UTC)
        run.status = "success"
        sheet_store.update_run(run)
        return 0
    raise ValueError(f"Unknown command: {args.command}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="dabud.ai AU SEO/GEO Job Intent Agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discover")
    sub.add_parser("enrich-contacts")
    sub.add_parser("generate-sequences")
    sub.add_parser("push-approved")
    run_all = sub.add_parser("run-all")
    run_all.add_argument("--push-approved", action="store_true", help="Also push approved rows to Snov")
    sub.add_parser("healthcheck")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(_run_command(args)))


if __name__ == "__main__":
    main()
