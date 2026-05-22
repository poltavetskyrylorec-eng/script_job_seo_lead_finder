# dabud.ai AU SEO/GEO Job Intent Agent

Production-oriented MVP for daily detection of Australian SEO/GEO/AEO/AI-search hiring intent, contact enrichment via Snov.io, personalized 4-email sequence generation (Claude CLI), manual approval in Google Sheets, and controlled push to Snov lists.

## What this agent does

1. Finds fresh AU job intent signals (`discover`) — Seek, Indeed, Jora via Playwright.
2. Normalizes and qualifies jobs, dedupes, classifies company type/track.
3. Resolves company domains (Claude + Snov fallback) and finds contacts via Snov.io (`enrich-contacts`).
4. Generates 4-email sequence per selected contact via Claude CLI (`generate-sequences`, no fallback).
5. Waits for human approval in Google Sheets (`approved=yes`).
6. Pushes only approved rows to Snov list (`push-approved`); campaigns pull from the list automatically.

Manual approval is mandatory. `DRY_RUN=true` (default) prevents real Snov push.

## Architecture

```text
Job boards (Seek / Indeed / Jora, Playwright)
    -> Normalizer + Qualification + Dedupe
        -> Google Sheets: pipeline + runs
            -> Domain lookup (Claude) + Snov contacts
                -> Claude CLI: 4-email sequences
                    -> Manual approval (approved=yes)
                        -> Snov list push
                            -> Campaign sends from list
```

## Project structure

```text
src/dabud_job_agent/
  config.py, main.py, models.py
  storage/          # Google Sheets
  sources/          # browser_provider (Playwright)
  integrations/     # claude, snov
  workflows/        # discover, enrich, generate, push
  agents/
  utils/
tests/
api/cron/           # legacy Vercel handlers
.github/workflows/
Dockerfile
render.yaml         # Render Cron Jobs (prod)
```

## Setup (local)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -e .[dev]
playwright install chromium
copy .env .env.local            # or create .env from scratch
```

Install [Claude Code CLI](https://code.claude.com/docs/en/setup) and set `CLAUDE_CODE_OAUTH_TOKEN`.

## Required env vars

| Variable | Purpose |
|---|---|
| `GOOGLE_SHEETS_SPREADSHEET_ID` | Target spreadsheet |
| `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64` | Service account JSON (base64) |
| `SNOV_CLIENT_ID` / `SNOV_CLIENT_SECRET` | Snov.io API |
| `SNOV_PLATFORM_LIST_ID` | List for platform track |
| `SNOV_PARTNER_LIST_ID` | List for partner track |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code OAuth token |

## Optional env vars

| Variable | Default | Notes |
|---|---|---|
| `DRY_RUN` | `true` | Set `false` for real Snov push |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Passed to `claude -p --model` |
| `JOB_SEARCH_PROVIDER` | `browser` | Playwright scraping (Seek/Indeed/Jora) |
| `SNOV_CAMPAIGN_ID` | — | Stored in sheet metadata; push goes to **list**, not campaign API |
| `TIMEZONE` | `Australia/Sydney` | Job lookback window |
| `RUN_LOOKBACK_HOURS` | `24` | Only jobs from last N hours |
| `MAX_CONTACTS_PER_COMPANY` | `2` | Snov contact cap per company |

## Google Sheets

Tabs auto-created on first run: `pipeline`, `runs`.

`runs` includes `claude_cost_usd` (estimated Claude cost per run).

Share the spreadsheet with the service account email from your JSON key.

## Snov.io

1. Create API app, set client ID/secret.
2. Create lists for platform and partner tracks.
3. Custom fields: the agent maps logical keys (`email_1_subject`, etc.) to your account's actual field names (including localized names like Ukrainian). Create fields in Snov for subjects/bodies or rely on dynamic mapping.
4. Push target is **list** (`add-prospect-to-list`). Your campaign should be configured to pull from that list.

## Commands

```bash
python -m dabud_job_agent.main healthcheck
python -m dabud_job_agent.main discover
python -m dabud_job_agent.main enrich-contacts
python -m dabud_job_agent.main generate-sequences
python -m dabud_job_agent.main push-approved
python -m dabud_job_agent.main run-all              # discover + enrich + generate
python -m dabud_job_agent.main run-all --push-approved   # also push approved (usually separate cron)
```

`run-all` does **not** push by default — use `push-approved` on its own schedule after manual approval.

## Manual approval

1. Review rows in `pipeline`.
2. Set column `approved` to `yes` for rows to send.
3. Run `push-approved` (or wait for cron).
4. Only rows with `approved=yes`, `send_status=not_sent`, and valid `contact_email` are pushed.

## Production deploy (GitHub Actions)

Primary prod target: **GitHub Actions** cron workflows (`.github/workflows/`).

| Workflow | Schedule (UTC, Kyiv UTC+3 summer) | Command |
|---|---|---|
| `run-all.yml` | `0 23 * * *` → 02:00 Kyiv | `python -m dabud_job_agent.main run-all` |
| `push-approved.yml` | `0 6,12,21 * * *` → 09:00, 15:00, 00:00 Kyiv | `python -m dabud_job_agent.main push-approved` |

Steps:
1. Push repo to GitHub.
2. Repo → **Settings → Secrets and variables → Actions** → add repository secrets (see table below).
3. **Actions** tab → select workflow → **Run workflow** to test manually.
4. Cron starts automatically after the first push to the default branch.

Winter (Kyiv UTC+2): shift cron +1 hour UTC in the workflow files.

| Secret | Required |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | yes |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | yes |
| `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64` | yes |
| `SNOV_CLIENT_ID` / `SNOV_CLIENT_SECRET` | yes |
| `SNOV_PLATFORM_LIST_ID` / `SNOV_PARTNER_LIST_ID` | yes |
| `SNOV_CAMPAIGN_ID` | optional |

Private repo free tier: 2,000 Actions minutes/month (~33 h). Full daily `run-all` (~90 min) uses ~2,700 min/month — expect ~$5–8 overage on GitHub Free, or make the repo public for unlimited minutes.

## Alternative: Render

`render.yaml` — Render Cron Jobs with Docker (Playwright + Claude CLI). Same cron schedule as above.

## Legacy: Vercel

- `vercel.json` + `api/cron/` — 5 min timeout, **not suitable** for full pipeline.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Healthcheck failed` | Missing env vars or Sheets access |
| `Claude CLI failed code=1` | Session usage limit (subscription cap) |
| `ClaudeEmailGenerationError` | No fallback — fix Claude auth or retry later |
| `contact_status=no_contact_found` | No Snov prospects for domain |
| `Snov push 422` | Custom field mismatch (check mapping logs) |
| Empty `source` rows in pipeline | Fixed in latest storage logic — re-run on clean sheet |

## Compliance

- Public pages only; no CAPTCHA/login bypass.
- Rate limits respected (Sheets cache, batch updates, retries).
- Never commit `.env` or service account JSON.
