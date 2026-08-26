# Telegram Weekly Meal Planner Agent

Personal/family weekly meal-planning bot for Telegram. Every configured week it creates a draft menu, discusses revisions with one admin user in Turkish natural language, and publishes the approved final menu plus a consolidated shopping list to configured recipients.

The app uses persistent application-level memory. It does not rely on fine-tuning: recipes, meal history, feedback, hard preferences, soft preferences, pantry staples, and workflow state live in SQLAlchemy tables.

## What It Does

- Runs on a configurable weekly schedule, default Sunday 10:00 Europe/Istanbul.
- Creates exactly one planning session per week.
- Sends draft menus only to `ADMIN_TELEGRAM_USER_ID`.
- Accepts Turkish revision messages such as `Salıdaki balığı çıkar. Çarşambaya kuru fasulye koy.`
- Supports approval by inline button, `/approve`, or natural language like `onaylıyorum`.
- Sends final menu and shopping list to `TELEGRAM_RECIPIENT_CHAT_IDS`.
- Learns through recipe library, meal history, feedback history, hard preferences, and soft preferences.

## Architecture

- `app/db`: SQLAlchemy models and database setup.
- `app/recipes`: YAML/JSON import, Telegram plain-text recipe parsing, future importer/discovery interfaces.
- `app/memory`: hard/soft preferences and feedback history.
- `app/planner`: candidate retrieval, scoring, structured planning, validation, minimal revision engine.
- `app/llm`: provider abstraction plus OpenAI implementation and deterministic fallback.
- `app/shopping`: unit normalization, serving scaling, pantry handling, ingredient aggregation.
- `app/bot`: Telegram commands, inline buttons, security, natural-language intent routing.
- `app/scheduler`: APScheduler weekly job with idempotent DB workflow.

## Setup

Create a Telegram bot with [@BotFather](https://t.me/BotFather), copy the token, then create `.env`:

```bash
cp .env.example .env
```

Fill in:

```env
TELEGRAM_BOT_TOKEN=123456:...
ADMIN_TELEGRAM_USER_ID=111111111
TELEGRAM_RECIPIENT_CHAT_IDS=111111111,222222222
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

To find Telegram IDs, send a message to your bot and check logs, or use a helper bot such as `@userinfobot`. Group chat IDs are usually negative numbers.

## Run With Docker

```bash
docker compose up -d --build
docker compose exec meal-planner-agent python -m app.cli init-db
docker compose exec meal-planner-agent python -m app.cli import-recipes data/recipes
```

Data is persisted through the bind-mounted `./data` directory. Back up `data/mealplanner.db` regularly:

```bash
cp data/mealplanner.db data/mealplanner.backup.$(date +%Y%m%d).db
```

## Local Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.cli init-db
python -m app.cli import-recipes data/recipes
python -m app.cli run
```

Manual draft generation:

```bash
python -m app.cli plan-now
```

## Initial Recipes

Example Turkish recipes live in `data/recipes/examples.yaml`. Replace that file or add your own `.yaml`, `.yml`, or `.json` files under `data/recipes`.

Import is idempotent:

```bash
python -m app.cli import-recipes data/recipes
```

## Teaching Recipes In Telegram

Admin-only:

```text
/addrecipe Etli kuru fasulye
500 gr kuru fasulye
300 gr kuşbaşı et
2 soğan
1 yemek kaşığı salça
```

Natural language also works:

```text
Bu tarifi kaydet:
Etli kuru fasulye
500 gr kuru fasulye
...
```

Commands: `/recipes`, `/recipe <name>`, `/addrecipe`, `/deleterecipe <name>`.

## Preferences

Hard preferences are explicit permanent rules, for example:

```text
Bundan sonra kereviz önerme.
```

Soft preferences come from repeated feedback and affect scoring without becoming permanent bans. Feedback such as `Bu yemeği geçen hafta yedik` is stored and lowers future repetition.

Commands: `/preferences`, `/addpreference <rule>`, `/deletepreference <rule>`.

## Pantry

Use `/pantry`, `/pantryadd <malzeme>`, `/pantryremove <malzeme>`.

`PANTRY_MODE=exclude` removes staples from the main shopping list. `PANTRY_MODE=check` shows them under `Evde kontrol et`.

## Scheduling

Configure:

```env
TIMEZONE=Europe/Istanbul
WEEKLY_PLAN_DAY=sunday
WEEKLY_PLAN_TIME=10:00
```

APScheduler registers the weekly job on startup. The job is idempotent, and `weekly_planning_sessions.week_start` has a unique constraint so restarts cannot create two independent sessions for the same week.

## SQLite To PostgreSQL

The default is:

```env
DATABASE_URL=sqlite:///data/mealplanner.db
```

For PostgreSQL later, install a PostgreSQL driver, switch to a URL such as:

```env
DATABASE_URL=postgresql+psycopg://user:password@host:5432/mealplanner
```

Then add Alembic migrations under `app/db/migrations`. The first version uses `python -m app.cli init-db` for simple personal deployment.

## Tests

```bash
pytest
```

Tests mock external Telegram/LLM behavior and cover planner preferences, repetition, revisions, shopping aggregation, workflow idempotency, authorization, and persistence.

## Current Limitations

- OpenAI is the only network LLM provider implemented; a deterministic fallback is used when no key is configured.
- URL recipe ingestion and web recipe discovery are interface-ready but intentionally not active by default.
- Natural-language understanding is Turkish-oriented with LLM support and rule-based fallback; uncertain permanent rules should be clarified by the admin.

