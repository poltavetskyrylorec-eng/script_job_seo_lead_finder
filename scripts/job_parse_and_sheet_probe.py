from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from dabud_job_agent.agents.company_classifier import classify_company
from dabud_job_agent.agents.company_researcher import enrich_company
from dabud_job_agent.agents.job_normalizer import normalize_job
from dabud_job_agent.config import get_settings
from dabud_job_agent.sources.browser_provider import BrowserSearchAdapter
from dabud_job_agent.storage.google_sheets import GoogleSheetsStore
from dabud_job_agent.utils.dedupe import dedupe_jobs, merge_jobs_by_company_signal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone probe: parse job vacancies and write sample rows to Google Sheets."
    )
    parser.add_argument("--query", default="SEO specialist", help="Search query.")
    parser.add_argument("--location", default="Australia", help="Search location.")
    parser.add_argument("--max-write", type=int, default=5, help="Max rows to write into sheet.")
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Parse only, do not write to Google Sheets.",
    )
    return parser.parse_args()


async def run_probe(args: argparse.Namespace) -> None:
    settings = get_settings()
    adapter = BrowserSearchAdapter(settings)
    sheet = GoogleSheetsStore(
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
        service_account_json_base64=settings.google_service_account_json_base64,
    )
    sheet.ensure_tabs()

    raw = await adapter.fetch_jobs(
        query=args.query,
        location=args.location,
        since=datetime.now(UTC),
    )
    run_id = f"probe-{uuid4()}"
    normalized = [normalize_job(item, run_id=run_id) for item in raw]
    deduped = dedupe_jobs(normalized)
    deduped = merge_jobs_by_company_signal(deduped)
    enriched = [classify_company(enrich_company(job)) for job in deduped]

    print("=== Probe parse result ===")
    print(f"raw_jobs={len(raw)}")
    print(f"deduped_jobs={len(deduped)}")
    if enriched:
        print(f"sample_title={enriched[0].job_title}")
        print(f"sample_source={enriched[0].job_board_source or enriched[0].source}")
        print(f"sample_url={enriched[0].job_url}")

    if args.no_write:
        print("write_status=skipped (--no-write)")
        return

    to_write = enriched[: max(0, args.max_write)]
    sheet.append_leads(to_write)
    print(f"write_status=ok rows_written={len(to_write)} run_id={run_id}")


def main() -> None:
    args = parse_args()
    asyncio.run(run_probe(args))


if __name__ == "__main__":
    main()
