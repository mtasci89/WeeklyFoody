import pytest

from app.db.models import WeeklyPlanningSession
from app.recipes.importer import IngredientInput, RecipeInput
from app.recipes.service import RecipeService
from tests.test_app_api import AUTH, _plan, api_settings, client, factory


@pytest.mark.asyncio
async def test_android_shopping_response_groups_aliases_without_changing_recipes(client, factory, settings):
    session_id = await _plan(factory, settings)
    names = ['dana kuşbaşı', 'kuşbaşı dana eti', 'kuşbaşı et']
    with factory() as db:
        session = db.get(WeeklyPlanningSession, session_id)
        targets = sorted((i for i in session.meal_plan.items if i.recipe.category == 'main'), key=lambda i: i.date)[:3]
        for item, name, amount in zip(targets, names, [800, 500, 800]):
            recipe = RecipeService(db).upsert_recipe(RecipeInput(name='Alışveriş testi ' + name, ingredients=[IngredientInput(name=name, quantity=amount, unit='g')]))
            item.recipe_id, item.recipe = recipe.id, recipe
        db.commit()
    response = client.get('/api/v1/alisveris', headers=AUTH)
    assert response.status_code == 200, response.text
    rows = [i for group in response.json()['gruplar'] for i in group['kalemler']]
    beef = [i for i in rows if i['ad'] == 'dana kuşbaşı']
    assert len(beef) == 1
    assert beef[0]['metin'] == '2,1 kg dana kuşbaşı'
    assert beef[0]['anahtar'] == 'dana kuşbaşı|g'
    assert not any(i['ad'] in ['kuşbaşı dana eti', 'kuşbaşı et'] for i in rows)
    with factory() as db:
        for name in names:
            assert RecipeService(db).find_recipe('Alışveriş testi ' + name).ingredients[0].ingredient.name == name
