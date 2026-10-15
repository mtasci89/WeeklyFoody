This first personal-app version uses SQLAlchemy `create_all` during startup and `python -m app.cli init-db`.

The models are intentionally PostgreSQL-friendly. When schema evolution becomes necessary, add Alembic here and set
`DATABASE_URL` to a PostgreSQL URL such as `postgresql+psycopg://user:pass@host/db`.


## 2026-10-15: per-serving nutrition

`RecipeNutrition` adds a separate `recipe_nutrition` table, linked by recipe ID.
`init-db` / application startup creates it using `create_all`. Existing recipe
and preference tables require no ALTER or data rewrite. Missing nutrition rows
mean unknown values, not zero. This additive upgrade is tested against an
existing SQLite schema; a live PostgreSQL upgrade has not been executed.

Rule editing continues to use the existing `preferences` table (soft deletion
of removed rules); there is no separate Markdown/JSON rule store to synchronise.
