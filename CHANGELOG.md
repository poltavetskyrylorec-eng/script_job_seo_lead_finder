# Історія змін — dabud.ai AU SEO/GEO Job Intent Agent

Хронологічний журнал розробки проєкту. Джерела: діалоги в Cursor, стан репозиторію, README.

Формат: **[YYYY-MM-DD]** — короткий опис змін.

---

## 2026-05-25

### Документація та інструменти
- Створено цей файл `CHANGELOG.md` для ведення історії змін по датах.

---

### Stabilization pipeline (Codex, 2026-05-25)

**Changed**
- `run-all` no longer creates a duplicate run row in `runs`: `run_discover(...)` now accepts current `RunStats` and keeps a single `run_id`.
- Added end-to-end technical key `lead_id` in models:
  - `JobPosting`
  - `Contact`
  - `EmailSequence`
- `lead_id` is now generated in `discover` as a stable hash within run (`run_id + stable_job_key`) and propagated through `discover -> enrich -> generate -> push`.

**Fixed**
- In `push_approved_to_snov`, lead mapping now prioritizes `(run_id, lead_id)` to avoid selecting the wrong lead row when company/domain repeats in one run.
- Added precise multi-column Google Sheets updates:
  - new `GoogleSheetsStore.update_rows_where(...)`,
  - push updates now use `run_id + lead_id + contact_email` with backward-compatible fallback.
- Added safe enum fallbacks in `generate_sequences` for invalid sheet values (`company_type`, `outreach_track`) to prevent workflow crashes.

**Changed (migration safety)**
- `lead_id` was added to pipeline schema safely at the end of `LEADS_COLUMNS` to avoid shifting existing historical data columns.

**Tests / Docs**
- Updated `tests/test_google_sheet_mapping.py` for current column order.
- Added `tests/test_generate_sequences_mapping.py` (safe enum fallback + `lead_id` mapping check).
- Updated `README.md`:
  - documented `lead_id` purpose,
  - added troubleshooting note for wrong row updates.

---

## 2026-05-22

### Production deploy
- Додано файли для prod-розгортання:
  - `Dockerfile` (Playwright + Claude CLI)
  - `render.yaml` (Render Cron Jobs — альтернатива GitHub Actions)
  - `.github/workflows/run-all.yml` — повний pipeline (`discover → enrich → generate`)
  - `.github/workflows/push-approved.yml` — push затверджених контактів у Snov
- Оновлено cron-розклад (літній час Kyiv, UTC+3):
  - **02:00** — `run-all`
  - **09:00, 15:00, 00:00** — `push-approved`
- GitHub Actions: Playwright `--with-deps chromium`, Node.js, глобальний `@anthropic-ai/claude-code`.
- Діагностика та виправлення **GitHub Secrets** (`SpreadsheetNotFound 404` — неправильний формат ID/base64 у secrets vs локальний `.env`).

### Якість даних у Google Sheets
- Виправлено **«порожні» рядки без `source`** у вкладці `pipeline`:
  - причина: `append_contacts` / `append_sequences` створювали contact-only/sequence-only рядки без метаданих вакансії;
  - fix: оновлення існуючого lead-рядка замість `append_row` без контексту.
- Обмеження `enrich` / `generate` **поточним `run_id`** (без обробки історичного backlog у `run-all`).
- Новий статус **`skipped_invalid_company`** для рядків з `Unknown`/порожньою компанією.
- Дедуплікація контактів (email + domain + run) у `contact_selector`, `enrich_contacts`, `generate_sequences`.
- Прив’язка sequence до конкретного ліда через **`job_url`** (уникнення перезапису «чужих» рядків).
- **`lead_id`** — стабільний внутрішній ключ ліда для точного матчингу між discover/enrich/generate/push.
- Timeout GitHub workflow **`run-all`**: 180 → **360 хвилин**.

### Генерація листів
- Генерація **тільки** якщо є ім’я контакту, компанія та email.
- Пропуск рядків, де поля `email_1..email_4` уже заповнені (без перегенерації).
- Окремий локальний прогін `generate-sequences` (~44 хв) — успішно завершено.

### Операційні питання
- Інструкція тимчасового **вимкнення cron** на GitHub (Disable workflow у Actions).
- Розбір проблеми **Snov push через GitHub vs локально** (фільтри `approved=yes`, `send_status=not_sent`, перегляд List, а не Campaign).
- Аудит `jobs_parse_au - pipeline.csv`: дублікати, `Unknown` компанії, aggregator URLs, тривалість run (~3 год).
- Оцінка ринкової вартості проєкту (~$6k–$30k, ~250–400 dev-год).

---

## 2026-05-21

### End-to-end тестування на реальних даних
- Перехід від mock/тестових даних до **повного прогону на live job boards**.
- Перший успішний E2E: discover → Sheets → domain → Snov enrich → Claude emails → push.
- Успішний push **2 approved** контактів у Snov list (`darlene.powell@nutraorganics.com.au`, `marianna@theonset.com.au`).

### Domain lookup та контакти
- Пошук домену компанії через **Claude web search** (назва → домен).
- Fallback: **Snov domain search**, якщо Claude не знайшов.
- Виправлено проблеми з **Claude CLI** (не відповідав / auth).
- Оновлено **Tier 1/2/3** пріоритети посад для Snov contact selection (practice manager, CMO, head of SEO тощо).

### Snov.io інтеграція
- Push переведено на **`add-prospect-to-list`** (кампанія тягне з list автоматично).
- **Динамічний мапінг custom fields** під реальні поля акаунту (укр. назви: `тема листа`, `4 лист тема` тощо).
- Виправлено 422 через невідповідність ключів `email_1_subject` vs фактичні поля Snov.

### Google Sheets та продуктивність
- Оптимізація **429 rate limit**: кеш читання листа в межах одного run (менше `get_all_records()`).
- Прибрано штучні ліміти обробки — enrichment для всіх qualified лідів.
- Колонка **`claude_cost_usd`** у вкладці `runs` (оцінка вартості Claude за прогін).
- Fix placeholder **`[First Name]`** → реальне ім’я контакту в листах.

### Job boards
- Виправлено збір **лише з Seek** — додано fallback по відсутніх boards (`indeed`, `jora`).
- Breakdown по source у `runs.notes`: `raw_src`, `dedupe_src`, `qualified_src`.
- Аналіз платформ deploy: **GitHub Actions** рекомендовано як primary (Vercel — legacy, 5 хв timeout).

### Результат референсного E2E run
- `jobs_found_raw`: 405 → `jobs_after_dedupe`: 32 → `jobs_qualified`: 8
- `contacts_found`: 4, `sequences_generated`: 5, `approved_pushed_to_snov`: 2
- `claude_cost_usd`: ~0.10

---

## 2026-05-20

### Архітектура під автономну роботу
- Уточнено ціль: **Vercel cron**, щоденний запуск о **06:00 Kyiv**, manual approval у Sheets.
- Підтверджено: **Playwright + Chromium** як основний job provider (Apify — опційно пізніше).
- Перехід з 3 на **4 email** у sequence (за `SKILL_email_v4.md`).
- Один операційний аркуш **`pipeline`** + технічний **`runs`** (замість окремих leads/contacts/sequences).

### Vercel (legacy)
- `api/cron/discovery.py` — discover + enrich + generate
- `api/cron/push_approved.py` — push approved
- `vercel.json` — cron `03:00 UTC` (06:00 Kyiv) + push кожні 6 год

### Google Sheets
- Налаштування **Google Cloud service account** (покрокова допомога в консолі).
- Заповнено `.env`: `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64`, доступ service account до таблиці.
- Перевірка запису в таблицю — **успішно**.
- Fix серіалізації `datetime`/`date` у `_model_to_row`.

### Claude
- Налаштування **Claude Code OAuth token** (`CLAUDE_CODE_OAUTH_TOKEN`).
- Окремий тест Claude CLI — успішно.

### Job scraping
- Інтеграція з **`dabud-jobboard-scraper.md`**: AU job boards, search queries, compliance rules.
- **`browser_provider.py`**: прямий парсинг Seek, Indeed AU, Jora AU + SERP fallback.
- Колонки **`job_board_source`**, **`geo_aeo_status`** (`NEW_REVENUE` / `UPGRADE` / `COMPETITOR` / `NEUTRAL`).
- AU **User-Agent** і env-конфігурація перевірені.
- Скрипти:
  - `scripts/sheets_rate_limit_probe.py` — probe Google Sheets 429
  - `scripts/job_sites_availability_probe.py` — доступність job boards
  - `scripts/job_parse_and_sheet_probe.py` — парсинг + запис у Sheets
- Аналіз: **Claude не замінює Playwright** для щоденного discovery (гібридний підхід).

---

## 2026-05-19

### Створення проєкту (MVP v0.1.0)
- Ініціалізація репозиторію **`script_job_seo_lead_finder`** / пакет **`dabud-au-job-agent`**.
- Мета: щоденний AU hiring-intent agent для SEO/GEO/AEO/AI Search → Snov outreach з manual approval.

### Архітектура
```
src/dabud_job_agent/
  config.py, main.py, models.py, logging_config.py
  storage/       — Google Sheets (+ SQLite cache для dedupe)
  sources/       — search_provider, seek/indeed/jora/glassdoor/linkedin (disabled by default)
  integrations/  — claude, snov
  workflows/     — discover_jobs, enrich_contacts, generate_sequences, push_approved_to_snov
  agents/        — job_normalizer, company_classifier, company_researcher,
                   contact_selector, email_writer
  utils/         — dedupe, dates, text
tests/
api/cron/        — заготовка під serverless
.github/workflows/
```

### Функціональність MVP
- CLI: `healthcheck`, `discover`, `enrich-contacts`, `generate-sequences`, `push-approved`, `run-all`
- Pipeline: discover → qualify/dedupe/classify → enrich (Snov) → generate (Claude + fallback) → manual approve → push
- **`DRY_RUN=true`** за замовчуванням — блокує реальний Snov push
- Compliance-first: без CAPTCHA bypass, без LinkedIn profile scraping
- JSON-логування, pydantic models, tenacity retries

### Тести та CI
- `pytest`: dedupe, company classification, contact priority, snov payloads, dry-run, utils
- GitHub Actions: `daily-discovery.yml`, `push-approved.yml` (початкові workflow)
- `README.md`, `.env.example`, `.gitignore`, `pyproject.toml` (Python ≥3.11)

### Рефакторинг (в той же день)
- **Видалено SQLite** як primary storage — результати **тільки в Google Sheets** (за запитом користувача).
- Наступні кроки для користувача: налаштування Sheets, Claude, Snov, перший dry-run.

---

## Поточний стан (на 2026-05-25)

| Компонент | Статус |
|-----------|--------|
| Локальний pipeline | Працює |
| Google Sheets (`pipeline`, `runs`) | Працює |
| Playwright (Seek/Indeed/Jora) | Працює |
| Claude CLI (domains + 4 emails) | Працює |
| Snov enrich + list push | Працює |
| GitHub Actions cron | Налаштовано (може бути тимчасово вимкнено) |
| Vercel | Legacy (timeout 5 хв — не для повного pipeline) |
| Render | Альтернатива (`render.yaml`) |

### Основні CLI-команди
```bash
python -m dabud_job_agent.main healthcheck
python -m dabud_job_agent.main discover
python -m dabud_job_agent.main enrich-contacts
python -m dabud_job_agent.main generate-sequences
python -m dabud_job_agent.main push-approved
python -m dabud_job_agent.main run-all
```

---

## Як доповнювати цей файл

Після кожної значущої зміни додавай блок **`## YYYY-MM-DD`** на початок (після заголовка) з пунктами:
- **Added** — нове
- **Changed** — зміни в існуючому
- **Fixed** — виправлення багів
- **Docs / Ops** — документація, deploy, конфіг
