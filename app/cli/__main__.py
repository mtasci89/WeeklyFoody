from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.config import get_settings
from app.db.session import SessionLocal, init_db
from app.main import async_main
from app.planner.service import MealPlannerService
from app.recipes.service import RecipeService
from app.recipes.weekly_discovery import WeeklyRecipeDiscoveryService


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly meal planner agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    import_parser = sub.add_parser("import-recipes")
    import_parser.add_argument("path", type=Path)
    excel_parser = sub.add_parser("import-menu-excel")
    excel_parser.add_argument("path", type=Path)
    sub.add_parser("plan-now")
    sub.add_parser("discover-now")
    sub.add_parser("check-agent", help="Ajanin saglayicisina tek bir deneme istegi atar")
    app_parser = sub.add_parser("uygulama-hazirla", help="Foody uygulamasi icin HTTPS API'yi hazirlar")
    app_parser.add_argument("--adres", required=True, help="Telefonun baglanacagi adres, orn. https://152.67.69.25:8443")
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
    elif args.command == "discover-now":
        init_db()

        async def _discover() -> None:
            from app.agent.prompts import discovery_prompt
            from app.agent.runner import MealPlannerAgent

            if MealPlannerAgent.available(settings):
                # Telegram'daki haftalik kesifle ayni yol: ajan web'de arar.
                agent = MealPlannerAgent(settings, SessionLocal)
                try:
                    for query in settings.recipe_discovery_queries:
                        reply = await agent.reply(
                            settings.admin_telegram_user_id,
                            discovery_prompt(query, settings.recipe_discovery_limit_per_category),
                        )
                        print(reply.text, end="\n\n")
                finally:
                    await agent.aclose()
                return
            with SessionLocal() as db:
                candidates = await WeeklyRecipeDiscoveryService(db, settings).discover_candidates()
                print(f"Discovered {len(candidates)} candidate recipes")
                for recipe in candidates:
                    print(f"- {recipe.name} ({recipe.category})")

        asyncio.run(_discover())
    elif args.command == "uygulama-hazirla":
        from app.api_tls import prepare

        result = prepare(Path(".env"), args.adres, settings.app_api_cert, settings.app_api_key)
        print("Uygulama anahtari: " + ("yeni uretildi" if result["yeni_anahtar"] else "mevcut olan kullaniliyor"))
        print("Sertifika       : " + ("yeni uretildi" if result["yeni_sertifika"] else "mevcut olan kullaniliyor"))
        print(f"Sertifika pini  : {result['pin']}")
        print("Botu yeniden baslat, sonra Telegram'da /uygulama yaz: baglanti kodu oraya gelir.")
    elif args.command == "check-agent":
        raise SystemExit(asyncio.run(_check_agent(settings)))
    elif args.command == "run":
        asyncio.run(async_main())


async def _check_agent(settings) -> int:
    """Anahtar, model ve kota sorunlarini botu acmadan gosterir."""
    from app.agent.runner import MealPlannerAgent, explain_failure

    print(f"Saglayici : {settings.agent_provider}")
    if not MealPlannerAgent.available(settings):
        key = "GEMINI_API_KEY" if settings.agent_provider == "gemini" else "ANTHROPIC_API_KEY"
        print(f"SONUC     : KAPALI - .env icinde {key} yok ya da AGENT_ENABLED=false")
        return 1
    agent = MealPlannerAgent(settings, SessionLocal)
    try:
        if agent.provider == "gemini":
            # Zincirdeki her modeli tek tek dene: hangisi mesgul, hangisi
            # kapatilmis, hangisi calisiyor - tahmin etmeden gor.
            results = await agent.gemini.check_models()
            print("Modeller  : (ilk calisan kullanilir)")
            for model, ok, detail in results:
                print(f"  {'OK ' if ok else '-- '} {model:28s} {detail}")
            working = [model for model, ok, _ in results if ok]
            if working:
                print(f"SONUC     : CALISIYOR - bot {working[0]} ile cevap verecek")
                return 0
            print("SONUC     : HATA - zincirdeki hicbir model cevap vermedi")
            return 1
        print(f"Model     : {agent.model}")
        answer = await agent.ping()
    except Exception as error:
        print(f"SONUC     : HATA - {explain_failure(error)}")
        print(f"Ayrinti   : {type(error).__name__}: {str(error)[:300]}")
        return 1
    finally:
        await agent.aclose()
    print(f"SONUC     : CALISIYOR - model cevap verdi: {answer[:60]!r}")
    return 0


if __name__ == "__main__":
    main()
