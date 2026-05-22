from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime

from gspread.exceptions import APIError

from dabud_job_agent.config import get_settings
from dabud_job_agent.storage.google_sheets import GoogleSheetsStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe Google Sheets API rate limits by repeated calls."
    )
    parser.add_argument(
        "--tab",
        default="pipeline",
        help="Worksheet tab to read from (default: pipeline).",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        default=300,
        help="Maximum number of API calls to attempt (default: 300).",
    )
    parser.add_argument(
        "--sleep-ms",
        type=int,
        default=0,
        help="Sleep between calls in milliseconds (default: 0).",
    )
    parser.add_argument(
        "--warmup-ensure-tabs",
        action="store_true",
        help="Run ensure_tabs() before probing (recommended if tabs were changed).",
    )
    return parser.parse_args()


def is_429(error: APIError) -> bool:
    text = str(error).lower()
    return "429" in text or "quota exceeded" in text or "rate" in text


def main() -> None:
    args = parse_args()
    settings = get_settings()
    store = GoogleSheetsStore(
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
        service_account_json_base64=settings.google_service_account_json_base64,
    )

    if args.warmup_ensure_tabs:
        store.ensure_tabs()

    start = time.perf_counter()
    first_429_at_call: int | None = None
    first_429_elapsed_s: float | None = None
    ok_calls = 0
    errors = 0

    print(
        f"[{datetime.now(UTC).isoformat()}] Start probe: tab={args.tab}, "
        f"max_calls={args.max_calls}, sleep_ms={args.sleep_ms}"
    )

    for call_idx in range(1, args.max_calls + 1):
        try:
            _ = store.get_rows(args.tab)
            ok_calls += 1
            if call_idx % 10 == 0:
                elapsed = time.perf_counter() - start
                print(f"call={call_idx} ok elapsed_s={elapsed:.2f}")
        except APIError as exc:
            errors += 1
            elapsed = time.perf_counter() - start
            print(f"call={call_idx} api_error elapsed_s={elapsed:.2f} msg={exc}")
            if is_429(exc) and first_429_at_call is None:
                first_429_at_call = call_idx
                first_429_elapsed_s = elapsed
                break
        except Exception as exc:
            errors += 1
            elapsed = time.perf_counter() - start
            print(f"call={call_idx} error elapsed_s={elapsed:.2f} msg={exc}")
            if "pipeline" in str(exc).lower():
                print("hint=Try running with --warmup-ensure-tabs to auto-create expected tabs.")

        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000)

    total_elapsed = time.perf_counter() - start
    print("\n=== Probe summary ===")
    print(f"ok_calls={ok_calls}")
    print(f"errors={errors}")
    print(f"total_elapsed_s={total_elapsed:.2f}")
    if first_429_at_call is not None:
        print(
            f"first_429_at_call={first_429_at_call} "
            f"first_429_elapsed_s={first_429_elapsed_s:.2f}"
        )
    else:
        print("first_429_at_call=not_reached")


if __name__ == "__main__":
    main()
