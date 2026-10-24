# WeeklyFoody

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

## Konusma Ajani (tool-use)

Sohbet katmani bir arac dongusu uzerinde calisir. Donguyu kimin kosturacagi
`AGENT_PROVIDER` ile secilir:

- `gemini` (varsayilan): Google AI Studio'nun ucretsiz katmani. `GEMINI_API_KEY`
  ve `GEMINI_MODEL` kullanir; planlayici da ayni anahtarla calistigi icin tek
  anahtar yeter. Web aramasi Google Search grounding ile yapilir.
- `anthropic`: Claude. Ucretli; `ANTHROPIC_API_KEY` ve `ANTHROPIC_MODEL` ister.

Araclar saglayicidan bagimsizdir; ayni araclar iki yolda da kosar.

Kurulumu botu acmadan dogrulamak icin:

```bash
python -m app.cli check-agent
```

Saglayiciya tek bir istek atar ve sonucu yazar: calisiyor mu, anahtar mi
gecersiz, kota mi dolmus, model mi bulunamiyor.

Ucretsiz katmanda dakikalik istek siniri dusuktur ve tek bir kullanici mesaji
2-4 istek uretir. 429 alininca istemci kisa bekleyip tekrar dener; yine de
dolarsa bot "ucretsiz kota doldu" der. Model mesaji sabit bir niyet
listesine eslemek yerine su araclari kendisi secip sirayla cagirir:

| Arac | Ne yapar |
| --- | --- |
| `plan_hazirla` | Onerilen gun seklini ve rol basina PUANLANMIS aday havuzunu dondurur |
| `plan_kaydet` | Kurulan haftalik plani yazar; gunun sekli serbest |
| `plani_getir` | Aktif / bu hafta / gelecek hafta planini dondurur |
| `tarif_ara` | Tarif kutuphanesinde ada ve malzemeye gore arar |
| `tarif_detay` | Bir tarifin malzeme ve hazirlanisini dondurur |
| `ogun_degistir` | Plandaki bir ogunu gerekcesiyle degistirir |
| `alisveris_listesi` | Bir haftanin toplu listesini cikarir |
| `gecmis_getir` | Son haftalarda yapilanlari dondurur (tekrar onleme) |
| `kurallari_goster` / `kural_ekle` / `kural_sil` | Ev kurallarini okur / ekler / siler |
| `besin_degeri_kaydet` | Tariflerin kisi basi tahmini kalori ve proteinini kaydeder |
| `tarif_ekle` | Yeni tarifi ADAY olarak kutuphaneye yazar |
| `aday_tarifler` | Onay bekleyen adaylari listeler |
| `tarif_onayla` | Adayi onaylar, menulerde kullanilabilir olur |
| `tarif_cikar` | Tarifi pasiflestirir |
| `web_ara` / `web_search` | Internette tarif arar (Gemini: Google Search grounding, Claude: sunucu araci) |

Haftalik plani ajan kendisi kurar: `plan_hazirla` her slot icin puanlanmis
aday havuzunu verir (puan; son yapilma tarihi, red sayisi, protein tekrari ve
hafta ici/sonu hazirlik suresinden olusur), model haftayi kurar, `plan_kaydet`
tumunu dogrulayip yazar. Eksik slot, aday tarif, kategori uyusmazligi ya da
tekrarlanan satir varsa kaydetmez ve neyin yanlis oldugunu soyler.

`MEAL_COURSE_ROLES` haftanin **onerilen** seklidir, dayatma degil. "Her gun tek
meze olsun", "cumartesi sadece ana yemek", "pazar disaridayiz" gibi istekler
plana oldugu gibi yansir; araclar yalnizca dogrulugu denetler (tarif onayli mi,
kategori role uyuyor mu, tarih haftanin icinde mi), gunun kac ogunden
olusacagini denetlemez.

Deterministik katmanin hesapladigi skorlar ilk kez modele ulasiyor: onceden
yalnizca liste SIRASI olarak gidiyordu, puanin kendisi ve gecmis bilgisi
atiliyordu.

Boylece tek mesajda birden fazla adim atilabiliyor. Ornek:
`Salı balık olmasın, yerine geçen ay beğendiğimiz tavuklu şeyi koy` -> model
once `plani_getir`, sonra `gecmis_getir`, sonra `tarif_ara`, en son
`ogun_degistir` cagirir ve degisikligin gerekcesini yazar.

Anlama isini model, yazma isini deterministik arac fonksiyonlari yapar: model
uydurdugu bir tarifi menuye koyamaz, `tarif_ara` ile kutuphanede dogrulamak
zorundadir. Onaylanmis ve yayinlanmis planlar araclar tarafindan reddedilir;
onaylama yetkisi ajanda degildir (`/approve` ya da onay dugmesi).

Calistirmak icin `ANTHROPIC_API_KEY` yeterli. Anahtar yoksa ya da
`AGENT_ENABLED=false` ise bot eski niyet yonlendiricisine geri duser, boylece
ikisini yan yana karsilastirabilirsin.

Maliyet. Her istekte sabit olarak ~2.600 token arac semasi + ~1.400 token
sistem istemi gidiyor; bunlar 1 saatlik TTL ile onbellege alinir, cunku tek
bir kullanici mesaji 2-4 API cagrisi uretir ve hepsi ayni on-eki paylasir.

Asil degisken modeldir, saglayici degil. `ANTHROPIC_MODEL` ile ayarlanir:

| Model | Plan kuran tur | Ayda ~30 tur |
| --- | --- | --- |
| `claude-opus-5-5` | ~$0.095 | ~$2.90 |
| `claude-sonnet-5-5` | ~$0.048 | ~$1.45 |
| `claude-haiku-5-5` | ~$0.002 | ~$0.07 |

Pahali gelirse once modeli dusur; mimariye dokunmaya gerek yok. `AGENT_EFFORT`
dusurmek ve `AGENT_WEB_SEARCH_ENABLED=false` yapmak da harcamayi azaltir.

## Guvenlik Notlari

- Zamanlayici isleri hicbir ayar tasimaz; ayarlari kendileri ortamdan okur.
  Eskiden `settings.model_dump()` job argumani olarak geciliyordu ve
  APScheduler bunu jobstore tablosuna pickle'ledigi icin butun API
  anahtarlari veritabani dosyasina duz metin yaziliyordu.
- Web panel varsayilan olarak kapali; acilirsa `WEB_PANEL_TOKEN` zorunlu.
  Token bos oldugunda kontrol atlanmiyor, uygulama hic baslamiyor.
- Bot'ta genel hata yakalayici var: yakalanmamis istisnalar kullaniciya sakin
  bir mesaj, admin'e ozet, loga tam iz olarak doner.

## Architecture

- `app/agent`: Claude arac dongusu, arac tanimlari, sistem istemi, sohbet gecmisi.
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
GEMINI_MODEL=gemini-3.8-flash
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

## Foody Android Uygulaması

Yönetici arayüzü artık telefondaki **Foody** uygulaması (`android/`, Kotlin/Compose;
yapısı Financia ile aynı). Beyin sunucuda kalır: uygulama `app/api.py`'deki HTTPS
JSON API'si üzerinden menüyü, alışveriş listesini, tarifleri, kuralları ve
asistanı kullanır. Telegram botu çalışmaya devam eder (alıcılara onaylı menü,
haftalık bildirimler, bağlantı kodu).

| Ekran | Ne yapar |
| --- | --- |
| Menü | Haftanın günleri, öğünler, kişi başı kalori; öğün değiştirme; onay |
| Alışveriş | Kategorili liste, alınanları işaretleme, paylaşma |
| Asistan | Sohbet: menü kur, değiştir, onayla; web'de tarif bul; kural ve kiler yönet. Fotoğraf eklenebilir (galeriden ya da kamerayla): yemek listesi → tarifleri ekler, tarif sayfası → tarifi kaydeder |
| Tarifler | Kütüphane ve adaylar; web'de tarif arama; adayı onaylama/çıkarma; tarif detayı (kişi sayısına göre) |
| Kurallar | Ev kurallarını ekleme/silme, sistemin neyi denetlediği |

**Kurulum (bir kez):**
1. Mac'te `./deploy/uygulama-ac.sh` → sunucuda anahtar + sertifika üretir, 8443'ü açar, dener.
   Dışarıdan ulaşılamıyorsa Oracle'da 8443 için giriş kuralı eklemen gerekir (betik nasıl
   yapılacağını yazar).
2. GitHub'da **Releases → "Foody (son sürüm)" → foody.apk** dosyasını telefondan indirip kur.
3. Telegram'da bota `/uygulama` yaz; gelen `FOODY1.` kodunu uygulamada Ayarlar'a yapıştır.

**Güvenlik:** Alan adı olmadığı için sunucu kendinden imzalı sertifika kullanır; uygulama
bu sertifikanın açık anahtarını sabitler (pin), başka sertifikayla konuşmaz. İstekler
uzun bir uygulama anahtarıyla (`Authorization: Bearer`) yapılır. Uygulama yalnızca
`INTERNET` izni taşır (banka uygulamalarıyla uyum; CI denetler). Kod ve anahtar
telefonda şifreli saklanır.

**Derleme:** GitHub Actions (`.github/workflows/uygulama.yml`) her gönderimde API
sözleşme testlerini, Android testlerini çalıştırır, APK'yı derler ve `uygulama-son`
sürümüne koyar. Yerelde: `cd android && ./gradlew :app:testDebugUnitTest :app:assembleRelease`
(`android/local.properties` içinde `sdk.dir`).

## Oracle Sunucusu

Bot Oracle sunucusunda systemd servisi (`weeklyfoody`) olarak çalışıyor. Mac'ten:

```bash
./deploy/sunucu-guncelle.sh      # GitHub'daki son kodu kur, yeniden başlat (önce DB yedeği)
./deploy/sunucu-gunluk.sh 100    # son 100 günlük satırı (gizli değerler maskeli)
```

SELinux açık olduğu için sanal ortamın `bin` klasörü `bin_t` etiketi ister;
güncelleme betiği bunu her seferinde yapar.

## Web Panel

The app includes a token-protected web panel for browsing recipes, candidates and pantry items, editing persistent meal rules, and entering per-serving nutrition values. The panel token now also grants permission to edit rules and nutrition; keep it private.

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
GEMINI_MODEL=gemini-3.8-flash
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

The admin can ask the bot to discover new recipes. With the agent enabled
(`GEMINI_API_KEY` set) the bot really searches the web (Google Search
grounding), skips recipes already in the library, and saves what it read with
its source as a candidate. Without the agent it falls back to asking the model
for ideas from memory.

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
You can also just reply in chat: "ikincisini onayla", "fajitayı çıkar".

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

## Yemek Kurallarım — kalıcı kurallar

Her seferinde tekrar söylemek zorunda kalmamak için kalıcı kurallar. Telefondan,
Telegram üzerinden yönetilir; modele uğramadığı için Gemini kotası dolsa da çalışır:

```text
/kurallar                         listeyi numaralı gösterir + sistemin hangisini denetlediği
/kural_ekle Balık kullanma        tek kural ekler ("Tercih: ..." ile başlarsa yumuşak tercih)
/kural_sil 2                      numarayla ya da "/kural_sil balık" ile siler
/kurallari_yaz                    komutun altına her satıra bir kural: listeyi baştan yazar
/kurallari_yaz sil                hepsini siler
```

Sohbetten de olur: "bundan sonra balık kullanma" dediğinde ajan kuralı kendisi
ekler; "bu hafta balık olmasın" gibi tek seferlik isteklerde eklemez. Ajan her
mesajda güncel listeyi okur.

Kurallar `preferences` tablosunda saklanır; panelin **Yemek Kurallarım**
sayfası (`/preferences`) ve eski `/preferences`, `/addpreference`,
`/deletepreference` komutları aynı kayıtları kullanır. Mevcut menü otomatik
olarak yeniden yazılmaz; yeni bir taslak oluşturun.

Panelde **Yemek Kurallarım** (`/preferences`) sayfasına her satırda bir kural
yazıp kaydedin. Kurallar mevcut tercih veritabanında saklanır; yeni konuşmada
ve bot yeniden başlatıldığında korunur. Satırı düzenlemek kuralı değiştirir,
silmek devre dışı bırakır. Telegram'daki `/preferences`, `/addpreference <kural>`
ve `/deletepreference <kural>` aynı kayıtları kullanır. Mevcut menü otomatik
olarak yeniden yazılmaz; yeni bir taslak oluşturun.

Örnekler (kendiliğinden etkinleştirilmez):

```text
Balık kullanma
Her öğünde 3 farklı yemek olsun
Kalorilerini de yaz yanına
Kişi başı öğün en fazla 1000 kcal
Protein ağırlıklı olsun
```

- Yemek sayısı **her öğündeki farklı tarif sayısıdır**, 1–6 arasıdır. Üç
  yemek için otomatik şablon ana yemek + meze/salata + yan yemektir.
- Yasaklar, sayı ve kayıtlı kalori üst sınırı; otomatik planlama, ajanla
  kaydetme/değiştirme, revizyon, onay ve yayınlama sırasında kontrol edilir.
  Sonradan eklenen kuralla çelişen eski taslak onaylanamaz; önce düzeltin.
  Ajanın tamamen boş bıraktığı bir gün ("pazar dışarıdayız") yemek sayısı
  kuralını ihlal etmez; yazılan her öğün ise kurala uymak zorundadır.
- Kalori toplamı her yemekten **bir porsiyon / bir kişi** içindir. Ailenin kişi
  sayısıyla çarpılmaz. Porsiyon büyüklüğü bu kayıtların dayandığı porsiyon olmalıdır.
- Protein önceliği, kayıtlı gram değerleriyle aday puanını artırır. Değer yoksa
  yalnızca protein kaynağı türüyle nitel bir tercih yapılır; gram uydurulmaz.
- Kesin olmayan isteklere `Tercih:` ile başlayabilirsiniz. Diğer serbest
  metinler de saklanıp ajana iletilir; otomatik denetimi olmayan kurallar
  panelde açıkça işaretlenir. Her doğal dil ifadesi otomatik kısıta çevrilmez.
- Boş satırlar ve `#` başlıkları atlanır; `-`/`*` liste işaretleri kabul edilir.
  Çelişen yemek sayıları kaydedilmez. Birden fazla kalori sınırında en düşük
  sınır geçerlidir. Eski bir düzenleme formu, sonradan değişmiş kayıtların
  üzerine yazamaz; yazılan metin hata ekranında korunur.

### Porsiyon başına kalori ve protein

Tarifin panel sayfasında kalori (kcal), protein (g), kaynak/hesaplama notu ve
“tahmini değer” işaretini düzenleyebilirsiniz. Alanlara bütün tencerenin değil,
**bir porsiyonun** değerlerini girin. Sıfır ve bilinmeyen değer birbirinden
ayrıdır. Kaynak gereklidir; bilinmeyen sayılar hesaplanmış gibi gösterilmez.
İki sayı alanını boş bırakıp kaydetmek besin değerlerini kaldırır.

Kalori isteyen bir kural varsa (gösterim ya da sınır) sistem, değeri olmayan
tarifleri malzemelerinden tek bir model isteğiyle tahmin edip kaydeder: ajanın
plan kaydetme/gösterme/değiştirme adımlarında, `/menu`, `/regenerate` ve
haftalık otomatik planda. Ajan bir planı gösterdiğinde ya da değiştirdiğinde
cevabın altına gün gün kişi başı kalori özetini sistem ekler; modelin
yazmasına bırakılmaz. Ajan ayrıca `besin_degeri_kaydet` ile tek tek de
kaydedebilir. Bu kayıtlar `tahmini` işaretli ve
kaynağı "ajan tahmini" olarak tutulur; elle girilmiş (tahmini olmayan) bir
değerin üzerine yazılmaz. Menüde tahmin oldukları belirtilir.

Kalori sınırı etkinse, kalori bilgisi olmayan yemeklerden uygunluk garantisi
verilemez; uygun ve bilgisi tamamlanmış bir öğün oluşturulamıyorsa işlem açık
bir hata ile durur. Menü, kayıtlı değerlere göre denetlenir; tahmini değerler
menüde ayrıca belirtilir. Kalorileri yalnızca gösterme kuralında eksik veriler
“bilinmiyor” olarak görünür.

YAML/JSON tarif içe aktarmada isteğe bağlı `nutrition` alanı da kullanılabilir:

```yaml
nutrition:
  calories_kcal: 250  # Yalnızca biçimi gösteren örnek değer
  protein_g: 20
  source: "Kullandığınız etiket veya hesaplama kaynağı"
  estimated: true
```

`nutrition` alanı bulunmayan eski tarif dosyaları mevcut besin değerini
korur; açık `nutrition: null` değeri kaydı kaldırır. Örnek tariflere otomatik
kalori tahminleri eklenmez.

### Mevcut kurulumda güncelleme

Yeni `recipe_nutrition` tablosu `init-db` veya normal uygulama başlangıcında
`create_all` ile eklenir. Eski tarif/tercih tabloları değiştirilmez; veri
silinmez. Güncelleme sırasında eski ve yeni botu aynı anda çalıştırmayın.
Paneli kullanmak için mevcut Web Panel ayarları geçerlidir; bu özellik paneli
kendiliğinden açmaz veya `.env` dosyanızı değiştirmez.

```bash
python -m app.cli init-db
```

Bu komut yapılandırılmış veritabanına yazar. Üretim veritabanında çalıştırmadan
önce normal yedekleme/güncelleme sürecinizi uygulayın.

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
