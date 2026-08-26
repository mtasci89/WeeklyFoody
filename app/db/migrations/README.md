This first personal-app version uses SQLAlchemy `create_all` during startup and `python -m app.cli init-db`.

The models are intentionally PostgreSQL-friendly. When schema evolution becomes necessary, add Alembic here and set
`DATABASE_URL` to a PostgreSQL URL such as `postgresql+psycopg://user:pass@host/db`.

