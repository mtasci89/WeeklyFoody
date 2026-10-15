from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.models import Base


def _ensure_sqlite_parent(database_url: str) -> None:
    if database_url.startswith("sqlite:///"):
        path = database_url.replace("sqlite:///", "", 1)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)


def build_engine(settings: Settings | None = None):
    settings = settings or get_settings()
    database_url = normalize_database_url(settings.database_url)
    _ensure_sqlite_parent(database_url)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, connect_args=connect_args)


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


# Migration araci (Alembic) yok; create_all var olan tabloya sutun eklemiyor.
# Sonradan eklenen bos birakilabilir sutunlar burada, acilista eksikse eklenir.
ADDED_COLUMNS = {
    "recipes": {
        "calories_per_serving": "INTEGER",
        "protein_g_per_serving": "INTEGER",
    },
}


def ensure_columns(bind_engine) -> list[str]:
    """Var olan tablolara eksik sutunlari ekler. Ne eklendiyse dondurur."""
    added = []
    inspector = inspect(bind_engine)
    tables = set(inspector.get_table_names())
    with bind_engine.begin() as conn:
        for table, columns in ADDED_COLUMNS.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, sql_type in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
                    added.append(f"{table}.{name}")
    return added


def init_db(bind_engine=None) -> None:
    target = bind_engine or engine
    Base.metadata.create_all(target)
    ensure_columns(target)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
