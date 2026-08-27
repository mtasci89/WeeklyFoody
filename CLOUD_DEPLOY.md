# Cloud Deploy: Railway

GitHub stores the code. It does not keep the Telegram bot running by itself. To keep the bot alive when your computer is off, deploy it to a cloud service.

Recommended simple setup:

- GitHub repo: stores code.
- Railway service: runs the bot from the Dockerfile.
- Railway Postgres: stores recipes, feedback, weekly sessions, and history.

## Important

Run only one copy of the Telegram bot at a time. If the cloud bot is running, stop the local terminal bot, otherwise Telegram polling can conflict.

## 1. Create Railway Project

1. Go to [https://railway.com](https://railway.com).
2. Sign in with GitHub.
3. Create a new project.
4. Choose deploy from GitHub repo.
5. Select `mtasci89/WeeklyFoody`.
6. Railway should detect the `Dockerfile` and build the app.

## 2. Add Postgres

1. In the Railway project, click `New`.
2. Add `Postgres`.
3. Railway creates a `DATABASE_URL` variable for the database.

Use that Postgres `DATABASE_URL` for the bot service. The app automatically supports Railway's `postgresql://...` URL format.

## 3. Add Environment Variables

Open the bot service, then add variables. Do not put secrets in GitHub.

Required:

```env
TELEGRAM_BOT_TOKEN=...
ADMIN_TELEGRAM_USER_ID=...
TELEGRAM_RECIPIENT_CHAT_IDS=...
TIMEZONE=Europe/Istanbul
WEEKLY_PLAN_DAY=sunday
WEEKLY_PLAN_TIME=10:00
DATABASE_URL=${{Postgres.DATABASE_URL}}
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
DEFAULT_SERVINGS=4
MEAL_SLOTS=dinner
MEAL_COURSE_ROLES=main,meze,meze,side
PANTRY_MODE=exclude
LOG_LEVEL=INFO
RECIPE_DISCOVERY_ENABLED=true
RECIPE_DISCOVERY_DAY=saturday
RECIPE_DISCOVERY_TIME=18:00
RECIPE_DISCOVERY_LIMIT_PER_CATEGORY=2
```

If Railway does not accept the `${{Postgres.DATABASE_URL}}` reference from copy/paste, use its variable picker/reference UI to select the Postgres service's `DATABASE_URL`.

## 4. Deploy

After variables are saved, redeploy the service.

The app runs:

```bash
python -m app.cli run
```

because this is already the Dockerfile command.

## 5. Import Initial Recipes

The app initializes tables on startup, but recipe import is a one-time command.

In Railway, open the service shell or run a one-off command:

```bash
python -m app.cli import-recipes data/recipes
```

Your local Excel import is not automatically available in the cloud because that Excel file is on your computer. For cloud use, either:

- teach recipes through Telegram, or
- export/import a YAML recipe file into `data/recipes`, commit it, and run `import-recipes`.

## 6. Stop Local Bot

Once Railway is running, stop the local bot:

```bash
pkill -f "python -m app.cli run"
```

Then message your Telegram bot:

```text
/start
/regenerate
```

## Notes

- Railway deploys from GitHub, so future commits can auto-deploy.
- Memory is in Postgres, not on your laptop.
- If you use SQLite on a cloud service without a persistent disk, memory can be lost on redeploy. Use Postgres for cloud.
