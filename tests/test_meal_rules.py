from __future__ import annotations

from collections import Counter
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.models import Base, Feedback, Preference, PreferenceType, Recipe, SessionState, WeeklyPlanningSession
from app.db.session import init_db
from app.formatting import format_meal_plan
from app.memory.preferences import PreferenceService, PreferenceConflict
from app.memory.rules import MealRules, RuleViolation
from app.planner.candidate_selector import CandidateSelector
from app.planner.dates import next_week_start
from app.planner.revision import RevisionService
from app.planner.scorer import CandidateScorer
from app.planner.service import MealPlannerService
from app.recipes.importer import RecipeInput
from app.recipes.nutrition import NutritionInput, save_nutrition
from app.recipes.service import RecipeService
from app.web_panel import create_web_app
from app.workflow import WeeklyWorkflowService
from test_agent_tools import call, toolset  # shared mocked tool boundary

WEEK = next_week_start(timezone='Europe/Istanbul')


def set_rules(db, text):
    prefs = PreferenceService(db)
    prefs.replace_document(text, prefs.revision())


def nutrient_records(db, kcal=150):
    for recipe in RecipeService(db).list_recipes():
        save_nutrition(db, recipe, NutritionInput(calories_kcal=kcal, protein_g=10, source='Test fixture', estimated=True))
    db.commit()


def weekly_lines():
    return [f'{(WEEK+timedelta(days=i)).isoformat()}|dinner_{role}|{name}'
            for i in range(7) for role,name in [('main','Fırında Tavuk'),('meze','Haydari'),('side','Makarna')]]


@pytest.mark.parametrize('text,field,value', [
    ('3 farklı yemek olsun','dishes_per_meal',3),
    ('Her öğünde üç farklı yemek olsun','dishes_per_meal',3),
    ('Kalorilerini de yaz yanına','show_calories',True),
    ("bir kişi için öğün başı kalori 1000'i geçmesin",'max_kcal',1000),
    ('Kişi başı öğün en fazla 1000 kcal','max_kcal',1000),
    ('Protein ağırlıklı olsun','protein_priority',True),
])
def test_user_examples_have_explicit_meaning(text, field, value):
    rules = MealRules.parse([text])
    assert getattr(rules,field)==value and not rules.advisory


def test_unknown_and_soft_constraints_are_visible_not_claimed_as_enforced():
    rules=MealRules.parse(['Haftada iki kez kırmızı et'], ['Her öğünde 3 yemek olsun'])
    assert len(rules.advisory)==2
    assert rules.dishes_per_meal is None
    assert all('otomatik denetim yok' in line for line in rules.summary())


def test_conflicting_rule_save_is_atomic(db):
    set_rules(db,'Balık kullanma')
    with pytest.raises(RuleViolation):
        set_rules(db,'3 farklı yemek olsun\n4 farklı yemek olsun')
    assert PreferenceService(db).hard_rules()==['Balık kullanma']


def test_edit_delete_restart_and_stale_editor(db):
    prefs=PreferenceService(db)
    prefs.add('Protein ağırlıklı olsun', PreferenceType.SOFT, source='telegram',weight=2)
    old=prefs.revision()
    prefs.replace_document('# Kurallar\n- Balık kullanma\nTercih: Protein ağırlıklı olsun',old)
    assert len(prefs.active())==2
    with pytest.raises(PreferenceConflict):
        prefs.replace_document('Tavuk kullanma',old)
    with sessionmaker(bind=db.get_bind())() as reopened:
        assert MealRules.from_db(reopened).protein_priority
        assert MealRules.from_db(reopened).excluded
    prefs.replace_document('Tercih: Protein ağırlıklı olsun',prefs.revision())
    assert not MealRules.from_db(db).excluded
    assert prefs.active()[0].weight==2
    assert db.scalar(select(Preference).where(Preference.rule=='Balık kullanma')).active is False


@pytest.mark.parametrize('name,protein', [('Fırında Somon',None),('Levrek Izgara',None),('Tuna Salad','fish'),('Ton Balığı Salatası',None)])
def test_fish_ban_covers_types_and_species(db,name,protein):
    recipe=RecipeService(db).upsert_recipe(RecipeInput(name=name,protein_type=protein))
    assert MealRules.parse(['Balık kullanma']).excludes(recipe)
    candidates=CandidateSelector(db).select('dinner',['Balık kullanma'],WEEK)
    assert recipe.id not in {r.id for r in candidates}


@pytest.mark.asyncio
async def test_automatic_plan_obeys_ban_count_and_cap(db,settings):
    nutrient_records(db)
    set_rules(db,"Balık kullanma\nHer öğünde 3 farklı yemek olsun\nKişi başı öğün en fazla 500 kcal")
    plan=await MealPlannerService(db,settings).create_or_get_weekly_session(WEEK)
    assert len(plan.meal_plan.items)==21
    for day in {i.date for i in plan.meal_plan.items}:
        items=[i for i in plan.meal_plan.items if i.date==day]
        assert len({i.recipe_id for i in items})==3
        assert sum(i.recipe.nutrition.calories_kcal for i in items)<=500
        assert not any(MealRules.from_db(db).excludes(i.recipe) for i in items)
    assert '450 kcal' in format_meal_plan(plan)
    assert 'tahmini' in format_meal_plan(plan)


@pytest.mark.asyncio
async def test_missing_calories_block_automatic_plan_without_partial_session(db,settings):
    set_rules(db,'Kişi başı öğün en fazla 1000 kcal')
    with pytest.raises(RuleViolation,match='kalori verisi eksik'):
        await MealPlannerService(db,settings).create_or_get_weekly_session(WEEK)
    assert db.scalar(select(WeeklyPlanningSession)) is None


@pytest.mark.asyncio
async def test_agent_count_ban_and_calorie_validation_precedes_writes(db,settings,toolset):
    set_rules(db,'3 farklı yemek olsun\nBalık kullanma')
    lines=weekly_lines()
    assert 'kaydedildi' in await call(toolset,'plan_kaydet',ogunler=lines)
    session=MealPlannerService(db,settings).current_session(WEEK)
    before=[(i.id,i.recipe_id) for i in session.meal_plan.items]
    assert 'kaydedilmedi' in await call(toolset,'plan_kaydet',ogunler=lines[:-1])
    fish=[line.replace('Fırında Tavuk','Izgara Balık') for line in lines]
    assert 'yasak' in await call(toolset,'plan_kaydet',ogunler=fish)
    set_rules(db,'Kişi başı öğün en fazla 400 kcal')
    assert 'bilgisi eksik' in await call(toolset,'plan_kaydet',ogunler=lines)
    nutrient_records(db)
    assert 'sınırını aşıyor' in await call(toolset,'plan_kaydet',ogunler=lines)
    assert [(i.id,i.recipe_id) for i in session.meal_plan.items]==before
    set_rules(db,'Kişi başı öğün en fazla 450 kcal')
    assert 'kaydedildi' in await call(toolset,'plan_kaydet',ogunler=lines)
    assert '450 kcal' in await call(toolset,'plani_getir',hafta='gelecek_hafta')


@pytest.mark.asyncio
async def test_agent_swap_cannot_bypass_rules(db,settings,toolset):
    await call(toolset,'plan_kaydet',ogunler=weekly_lines())
    set_rules(db,'Balık kullanma')
    result=await call(toolset,'ogun_degistir',tarih=WEEK.isoformat(),yeni_tarif='Izgara Balık',gerekce='test',ogun_slotu='dinner_main')
    assert 'kaydedilmedi' in result
    assert db.scalar(select(Feedback)) is None
    assert MealPlannerService(db,settings).current_session(WEEK).meal_plan.items[0].recipe.name=='Fırında Tavuk'


@pytest.mark.asyncio
async def test_revision_rollback_preserves_all_meals_and_feedback(db,settings):
    nutrient_records(db,100)
    set_rules(db,'3 farklı yemek olsun\nKişi başı öğün en fazla 300 kcal')
    planner=MealPlannerService(db,settings)
    session=await planner.create_or_get_weekly_session(WEEK)
    before=[(i.id,i.recipe_id) for i in session.meal_plan.items]
    replacement=RecipeService(db).find_recipe('Izgara Balık')
    replacement.nutrition.calories_kcal=1000
    db.commit()
    with pytest.raises(RuleViolation):
        await RevisionService(db,settings).revise(session,'Çarşambaya Izgara Balık koy.')
    assert [(i.id,i.recipe_id) for i in session.meal_plan.items]==before
    assert db.scalar(select(Feedback)) is None


@pytest.mark.asyncio
async def test_rule_change_is_checked_on_approval_and_publish(db,settings):
    planner=MealPlannerService(db,settings)
    session=await planner.create_or_get_weekly_session(WEEK)
    set_rules(db,'3 farklı yemek olsun')
    with pytest.raises(RuleViolation): planner.approve(session)
    assert session.state!=SessionState.APPROVED
    set_rules(db,'')
    planner.approve(session)
    set_rules(db,'Kişi başı öğün en fazla 1000 kcal')
    class Notifier:
        async def send_message(self,*args,**kwargs): pytest.fail('Must not send')
    with pytest.raises(RuleViolation): await WeeklyWorkflowService(db,settings,Notifier()).publish_final(session)


def test_protein_preference_changes_scoring_with_real_values(db):
    recipes=RecipeService(db).list_recipes()[:2]
    for r,grams in zip(recipes,[5,40]):
        save_nutrition(db,r,NutritionInput(calories_kcal=200,protein_g=grams,source='Fixture'))
    db.commit()
    scorer=CandidateScorer(db)
    before=dict((r.id,score) for score,r in scorer.score_with_values(recipes,WEEK,Counter()))
    set_rules(db,'Protein ağırlıklı olsun')
    after=dict((r.id,score) for score,r in scorer.score_with_values(recipes,WEEK,Counter()))
    assert after[recipes[1].id]-before[recipes[1].id] > after[recipes[0].id]-before[recipes[0].id]


def test_additive_nutrition_schema_preserves_existing_recipes(tmp_path):
    engine=create_engine(f'sqlite:///{tmp_path / "old.db"}')
    tables=[t for t in Base.metadata.sorted_tables if t.name!='recipe_nutrition']
    Base.metadata.create_all(engine,tables=tables)
    with engine.begin() as conn:
        conn.execute(Recipe.__table__.insert().values(id='old',name='Eski tarif',servings=4))
    init_db(engine)
    init_db(engine)
    assert 'recipe_nutrition' in inspect(engine).get_table_names()
    with sessionmaker(bind=engine)() as session:
        old=session.get(Recipe,'old')
        assert old.name=='Eski tarif' and old.nutrition is None


class HiddenInputs(HTMLParser):
    def __init__(self,html):
        super().__init__(); self.values={}; self.feed(html)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='input' and attrs.get('type')=='hidden': self.values[attrs['name']]=attrs.get('value','')


@pytest.fixture
def panel(db,settings):
    return TestClient(create_web_app(settings.model_copy(update={'web_panel_token':'test&secret'}),sessionmaker(bind=db.get_bind(),expire_on_commit=False)))


def rule_form(panel):
    response=panel.get('/preferences',params={'token':'test&secret'})
    assert response.status_code==200
    return HiddenInputs(response.text).values


def test_editor_auth_csrf_persistence_and_conflict(panel,db):
    assert panel.get('/preferences').status_code==401
    assert panel.post('/preferences',data={'rules':'Balık kullanma'}).status_code==401
    form=rule_form(panel)
    assert panel.post('/preferences',data={**form,'csrf':'bad','rules':'Balık kullanma'}).status_code==403
    saved=panel.post('/preferences',data={**form,'rules':'Balık kullanma'})
    assert saved.status_code==200 and 'Kurallar kaydedildi' in saved.text
    assert 'no-store' in saved.headers['cache-control']
    assert MealRules.from_db(db).excluded
    conflict=panel.post('/preferences',data={**form,'rules':'Tavuk kullanma'})
    assert conflict.status_code==409 and 'Tavuk kullanma' in conflict.text
    fresh=rule_form(panel)
    assert panel.post('/preferences',data={**fresh,'rules':''}).status_code==200
    db.expire_all()
    assert not MealRules.from_db(db).excluded


def test_editor_escapes_unrecognised_rules(panel):
    form=rule_form(panel)
    response=panel.post('/preferences',data={**form,'rules':'<script>alert(1)</script>'})
    assert '<script>alert' not in response.text
    assert '&lt;script&gt;' in response.text and 'otomatik denetim yok' in response.text


def test_nutrition_form_validation_edit_and_clear(panel,db):
    recipe=RecipeService(db).find_recipe('Fırında Tavuk')
    url=f'/recipes/{recipe.id}'
    form=HiddenInputs(panel.get(url,params={'token':'test&secret'}).text).values
    bad=panel.post(url+'/nutrition',data={**form,'calories_kcal':'nan','source':'Etiket'})
    assert bad.status_code==422
    saved=panel.post(url+'/nutrition',data={**form,'calories_kcal':'250','protein_g':'30','source':'Etiket','estimated':'true'})
    assert saved.status_code==200 and '250 kcal' in saved.text
    db.expire_all()
    assert recipe.nutrition.protein_g==30
    assert panel.post(url+'/nutrition',data={**form,'calories_kcal':'400','source':'Eski form'}).status_code==409
    form=HiddenInputs(panel.get(url,params={'token':'test&secret'}).text).values
    assert panel.post(url+'/nutrition',data=form).status_code==200
    db.expire_all()
    assert recipe.nutrition is None


def test_recipe_reimport_preserves_nutrition_unless_explicit(db):
    service=RecipeService(db)
    recipe=service.upsert_recipe(RecipeInput(name='Yeni tarif',nutrition=NutritionInput(calories_kcal=200,source='Test')))
    service.upsert_recipe(RecipeInput(name='Yeni tarif',instructions='Yeni açıklama'))
    assert recipe.nutrition.calories_kcal==200
    service.upsert_recipe(RecipeInput(name='Yeni tarif',nutrition=None))
    assert recipe.nutrition is None


def test_fish_adjectives_and_combined_exclusions(db):
    for name in ['Somonlu Salata','Balıklı Pilav','Tavuklu Makarna']:
        r=RecipeService(db).upsert_recipe(RecipeInput(name=name))
        assert MealRules.parse(['Tavuk ve balık kullanma']).excludes(r)
    assert MealRules.parse(["bir kişi için öğün başı kalroi 1000'i geçmesin"]).max_kcal==1000


@pytest.mark.asyncio
async def test_calorie_cap_is_per_person_not_household_and_unknown_display(db,settings,toolset):
    nutrient_records(db,150)
    set_rules(db,'Kişi başı öğün en fazla 450 kcal')
    assert 'kaydedildi' in await call(toolset,'plan_kaydet',ogunler=weekly_lines())
    session=MealPlannerService(db,settings).current_session(WEEK)
    for item in session.meal_plan.items: item.servings=8
    db.commit()
    MealPlannerService(db,settings).approve(session)
    assert '450 kcal' in format_meal_plan(session)
    set_rules(db,'Kalorilerini yaz yanına')
    first=session.meal_plan.items[0].recipe
    save_nutrition(db,first,None); db.commit()
    assert 'toplam kalori bilinmiyor' in format_meal_plan(session)


@pytest.mark.asyncio
async def test_long_menu_is_sent_in_chunks(db,settings,toolset):
    from app.bot.handlers import reply_menu
    from app.formatting import TELEGRAM_LIMIT
    messages=[]
    class Message:
        async def reply_text(self,text,**kwargs): messages.append((text,kwargs))
    await reply_menu(Message(), ('Yemek: 200 kcal\n'*1000), reply_markup='approval')
    assert len(messages)>1 and all(len(text)<=TELEGRAM_LIMIT for text,_ in messages)
    assert messages[-1][1]['reply_markup']=='approval'
    assert all('reply_markup' not in kwargs for _,kwargs in messages[:-1])


@pytest.mark.asyncio
async def test_agent_context_refreshes_rules_without_new_conversation(db,settings,toolset):
    assert not toolset.ambient_context()[0]
    set_rules(db,'Balık kullanma')
    assert 'Balık kullanma' in toolset.ambient_context()[0]
    set_rules(db,'Her öğünde 3 farklı yemek olsun')
    hard,_,_=toolset.ambient_context()
    assert 'Balık kullanma' not in hard
    assert 'Her öğünde 3 farklı yemek olsun' in hard


@pytest.mark.asyncio
async def test_invalid_model_plan_falls_back_to_feasible_calorie_combination(db,settings):
    from app.llm.base import WeeklyPlanOutput, PlannedMeal
    nutrient_records(db,100)
    chicken=RecipeService(db).find_recipe('Fırında Tavuk')
    chicken.nutrition.calories_kcal=2000; db.commit()
    set_rules(db,'Her öğünde 3 farklı yemek olsun\nKişi başı öğün en fazla 400 kcal')
    planner=MealPlannerService(db,settings)
    class IgnoresLimit:
        async def generate_plan(self, context):
            return WeeklyPlanOutput(meals=[PlannedMeal(date=day,meal_slot=slot,recipe_id=(chicken.id if slot.endswith('main') else context['candidate_recipes_by_slot'][slot][0]['id'])) for day in context['dates'] for slot in context['meal_slots']])
    planner.llm=IgnoresLimit()
    session=await planner.create_or_get_weekly_session(WEEK)
    assert all(item.recipe_id!=chicken.id for item in session.meal_plan.items)


@pytest.mark.asyncio
async def test_duplicate_recipe_cannot_satisfy_three_dishes(db,settings,toolset):
    set_rules(db,'3 farklı yemek olsun')
    lines=[f'{(WEEK+timedelta(days=i)).isoformat()}|dinner_main_{j}|Fırında Tavuk' for i in range(7) for j in range(1,4)]
    assert 'farklı yemek olmalı' in await call(toolset,'plan_kaydet',ogunler=lines)
    assert MealPlannerService(db,settings).current_session(WEEK) is None
