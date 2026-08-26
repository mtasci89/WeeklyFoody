from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.config import get_settings
from app.db.session import SessionLocal, init_db
from app.main import async_main
from app.planner.service import MealPlannerService
from app.recipes.service import RecipeService


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly meal planner agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    import_parser = sub.add_parser("import-recipes")
    import_parser.add_argument("path", type=Path)
    excel_parser = sub.add_parser("import-menu-excel")
    excel_parser.add_argument("path", type=Path)
    sub.add_parser("plan-now")
    sub.add_parser("run")
    args = parser.parse_args()

    settings = get_settings()
    if args.command == "init-db":
        init_db()
        print("Database initialized")
    elif args.command == "import-recipes":
        init_db()
        with SessionLocal() as db:
            count = RecipeService(db).import_recipes(args.path)
            print(f"Imported {count} recipes")
    elif args.command == "import-menu-excel":
        init_db()
        with SessionLocal() as db:
            count = RecipeService(db).import_menu_excel(args.path)
            print(f"Imported {count} menu recipes")
    elif args.command == "plan-now":
        init_db()

        async def _plan() -> None:
            with SessionLocal() as db:
                session = await MealPlannerService(db, settings).create_or_get_weekly_session()
                print(f"Created/found session for {session.week_start}: {session.id}")

        asyncio.run(_plan())
    elif args.command == "run":
        asyncio.run(async_main())


if __name__ == "__main__":
    main()
