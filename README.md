# Telegram Weekly Meal Planner Agent

Personal/family weekly meal-planning bot for Telegram. Every configured week it creates a draft menu, discusses revisions with one admin user in Turkish natural language, and publishes the approved final menu plus a consolidated shopping list to configured recipients.

The app uses persistent application-level memory. It does not rely on fine-tuning: recipes, meal history, feedback, hard preferences, soft preferences, pantry staples, and workflow state live in SQLAlchemy tables.

## What It Does

- Runs on a configurable weekly schedule, default Sunday 10:00 Europe/Istanbul.
- Creates exactly one planning session per week.
- Sends draft menus only to `ADMIN_TELEGRAM_USER_ID`.
- Accepts Turkish revision messages such as `Salıdaki balığı çıkar. Çarşambaya kuru fasulye koy.`
- Plans each configured meal as `1 main + 2 meze/salad + 1 side` by default.
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
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
MEAL_COURSE_ROLES=main,meze,meze,side
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

## Run In The Cloud

If your computer is off, the local bot is off too. GitHub stores the code but does not run the bot continuously.

For an always-on setup, deploy the GitHub repo to Railway and use Railway Postgres for persistent memory. See [CLOUD_DEPLOY.md](CLOUD_DEPLOY.md).

## Web Panel

The app includes a small read-only web panel for browsing the recipe database, candidate recipes, pantry items, and preferences.

By default it runs on localhost only:

```env
WEB_PANEL_ENABLED=true
WEB_PANEL_HOST=127.0.0.1
WEB_PANEL_PORT=8000
WEB_PANEL_TOKEN=choose-a-private-token
```

For the Oracle VM setup, keep `WEB_PANEL_HOST=127.0.0.1` and open it through an SSH tunnel from your Mac:

```bash
ssh -L 8000:127.0.0.1:8000 -i "$HOME/Downloads/ssh-key-weeklyfoody1GB.key" opc@152.67.69.25
```

Then open:

```text
http://127.0.0.1:8000/?token=YOUR_TOKEN
```

Do not expose this panel publicly unless you also set a strong `WEB_PANEL_TOKEN` and restrict network access.

## Local Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.cli init-db
python -m app.cli import-recipes data/recipes
python -m app.cli run
```

## LLM Provider

Gemini is recommended for a free-tier first run:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
```

Create a key in [Google AI Studio](https://aistudio.google.com/app/apikey). Google currently lists Gemini 2.5 Flash input and output tokens as free of charge on the free tier, with limited access/rate limits.

OpenAI is also supported:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

If the configured provider fails because of quota, billing, or temporary network issues, the app falls back to the deterministic local planner so the weekly workflow does not stop.

Manual draft generation:

```bash
python -m app.cli plan-now
```

## Meal Structure

By default the bot creates four dishes for each configured meal:

```env
MEAL_SLOTS=dinner
MEAL_COURSE_ROLES=main,meze,meze,side
```

This means each dinner gets one main dish, two meze/salad dishes, and one side such as soup, pilaf, pasta, quinoa, or bulgur. To change the structure later, edit `MEAL_COURSE_ROLES`; for example `main,side` or `main,salad,side`.

## Revising A Menu In Telegram

After a draft is generated, write naturally to your own bot, not BotFather:

```text
Salıdaki balığı çıkar.
Çarşambaya kuru fasulye koy.
Cumartesi 6 kişi olacağız.
Bu hafta iki kere tavuk olmasın.
```

The revision engine preserves unrelated days and changes only the targeted dish where possible.

## Initial Recipes

Example Turkish recipes live in `data/recipes/examples.yaml`. Replace that file or add your own `.yaml`, `.yml`, or `.json` files under `data/recipes`.

Import is idempotent:

```bash
python -m app.cli import-recipes data/recipes
```

You can also import dish names from a historical Excel menu list:

```bash
python -m app.cli import-menu-excel "/path/to/Yemek Listesi_Final.xlsx"
```

This imports meal names as minimal recipes with `source=excel:<filename>`. Ingredients are intentionally left empty until you teach the detailed recipe later, so shopping-list quantities remain reliable.

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

## Discovering New Recipes

The admin can ask the bot to discover new recipe ideas with Gemini:

```text
/discover pratik tavuk yemeği
Yeni bir balık yemeği bul.
Bu hafta farklı şeyler öner.
```

Discovered recipes are saved as `candidate`, not trusted permanent recipes. Review them with:

```text
/candidates
```

Approve one into the permanent recipe library:

```text
/approverecipe Tavuk Fajita
```

This protects your library from filling up silently with recipes you have not approved.

The bot can also run weekly automatic discovery. By default it looks for current, healthy, unusual but home-cookable main dishes, side dishes, and meze/salad ideas every Saturday at 18:00 Europe/Istanbul. These are also saved as `candidate` and sent only to the admin for review:

```env
RECIPE_DISCOVERY_ENABLED=true
RECIPE_DISCOVERY_DAY=saturday
RECIPE_DISCOVERY_TIME=18:00
RECIPE_DISCOVERY_LIMIT_PER_CATEGORY=2
```

Run it manually when needed:

```bash
python -m app.cli discover-now
```

## Saving Recipes From Instagram Or Elsewhere

If you see a recipe on Instagram, YouTube, a website, or a message, send the name and any recipe text to the bot:

```text
/addrecipe Tavuk Fajita
https://www.instagram.com/reel/...
600 gr tavuk
2 biber
1 soğan
1 yemek kaşığı zeytinyağı
```

The link is stored as the recipe source. The app does not scrape Instagram directly; pasted recipe text and ingredients are parsed into the database.

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

- Gemini and OpenAI network providers are implemented; a deterministic fallback is used when no key is configured or a provider fails.
- URL recipe ingestion and web recipe discovery are interface-ready but intentionally not active by default.
- Natural-language understanding is Turkish-oriented with LLM support and rule-based fallback; uncertain permanent rules should be clarified by the admin.
