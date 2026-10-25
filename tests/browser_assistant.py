import json
from datetime import date, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright
html=(Path(__file__).resolve().parents[1] / 'app/panel.html').read_text().replace('__PANEL_TOKEN__','preview-token')
data={'can_publish':True,'reply':'','sessions':[{'id':'preview','label':'26 Ekim - 1 Kasım'}], 'plan':{'id':'preview','version':1,'state':'PUBLISHED','status':'Gönderildi','label':'26 Ekim - 1 Kasım','can_publish':True,'shopping':'🛒 Alışveriş Listesi\n\nSebze & Meyve\n- 6 adet domates\n- 2 adet soğan', 'days':[{'name':name,'label':(date(2026,10,26)+timedelta(days=i)).strftime('%d.%m'),'meals':[{'name':main,'role':'Ana yemek','servings':4,'changed':False},{'name':'Haydari','role':'Meze/salata','servings':4,'changed':False},{'name':'Çoban Salata','role':'Meze/salata','servings':4,'changed':False},{'name':'Bulgur Pilavı','role':'Yan','servings':4,'changed':False}]} for i,(name,main) in enumerate(zip(['Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi','Pazar'],['Fırında Tavuk','Izgara Balık','Kuru Fasulye','Sebze Yemeği','Izgara Köfte','Nohut','Mercimek Köftesi']))]}}
Path('artifacts').mkdir(exist_ok=True)
errors=[]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 page=browser.new_page(viewport={'width':1440,'height':1120})
 page.on('pageerror',lambda error: errors.append(str(error)))
 def handle(route):
  if '/api/assistant' in route.request.url:
   if route.request.method=='POST':
    body=route.request.post_data_json
    if body['action']=='chat':
     data['plan'].update(version=2,state='AWAITING_APPROVAL',status='Onay bekleyen taslak')
     for meal in data['plan']['days'][5]['meals']:meal['servings']=6
     data['reply']='Cumartesi için kişi sayısını 6 yaptım. Yeni taslağı inceleyip onaylayabilirsin.'
    elif body['action']=='approve':
     data['plan'].update(state='PUBLISHED',status='Gönderildi');data['reply']='Güncel menü ve alışveriş listesi gönderildi.'
   route.fulfill(json=data)
  else:route.fulfill(body=html,content_type='text/html')
 page.route('**/*',handle)
 page.goto('http://weeklyfoody.test/')
 page.get_by_text('Fırında Tavuk',exact=True).wait_for()
 assert page.locator('.day').count()==7
 assert page.locator('#approve').is_hidden()
 page.screenshot(path='artifacts/assistant-desktop.png',full_page=True)
 page.locator('[data-prompt="Cumartesi 6 kişi olacağız."]').click()
 assert page.locator('#message').input_value()=='Cumartesi 6 kişi olacağız.'
 page.locator('#message').press('Enter')
 page.get_by_text('Cumartesi için kişi sayısını 6 yaptım.',exact=False).wait_for()
 assert page.locator('#approve').is_visible()
 assert page.locator('.day').nth(5).get_by_text('Ana yemek · 6 kişi').is_visible()
 page.locator('#shopping').click()
 assert page.locator('#shopping-dialog').is_visible()
 page.locator('#close-shopping').click()
 page.locator('#approve').click()
 page.get_by_text('Güncel menü ve alışveriş listesi gönderildi.',exact=True).wait_for()
 assert page.locator('#approve').is_hidden()
 page.set_viewport_size({'width':390,'height':844})
 page.screenshot(path='artifacts/assistant-mobile.png',full_page=True)
 assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
 assert not errors,errors
 print('UI passed: 7 days, edit published menu, servings preview, shopping dialog, approval, mobile overflow, no JavaScript errors.')
 browser.close()
