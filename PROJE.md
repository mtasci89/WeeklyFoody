# WeeklyFoody — ortak proje rehberi

Bu dosya Claude ve Codex için kalıcı proje bağlamıdır. Güncel durum, son kontroller ve sıradaki iş [DEVIR.md](DEVIR.md) içinde tutulur. Her oturumda ikisini de okuyun. Ayrıntılı kullanım ve kurulum anlatımı [README.md](README.md), mevcut bulut kurulum rehberi [CLOUD_DEPLOY.md](CLOUD_DEPLOY.md) içindedir; aynı bilgileri burada tekrar çoğaltmayın.

## Amaç ve kapsam

WeeklyFoody, kişisel/aile kullanımı için Telegram üzerinden haftalık yemek planlayan bir Python uygulamasıdır. Yöneticiyle Türkçe revizyon yapar; onaylanan menüyü ve birleştirilmiş alışveriş listesini yapılandırılmış alıcılara gönderir. Tarifler, tercihler, geri bildirimler ve haftalık iş akışı SQLAlchemy veritabanında saklanır.

Bu rehberdeki mimari bilgileri yerel kaynak koduna dayanır. Canlı botun, bulut dağıtımının ve dış sağlayıcıların çalıştığı anlamına gelmez; doğrulama kapsamı DEVIR.md içinde belirtilir.

## Mevcut yapı

| Konum | Sorumluluk |
| --- | --- |
| `app/cli/__main__.py`, `app/main.py` | Komut satırı girişleri; bot, zamanlayıcı ve isteğe bağlı panelin başlatılması |
| `app/config.py` | Ortam değişkenleri ve `.env` üzerinden ayarlar; kod varsayılanlarının kaynağı |
| `app/bot/` | Telegram komutları, yetkilendirme, düğmeler ve mesaj yönlendirme |
| `app/agent/` | Gemini/Anthropic sohbet ajanı, araç döngüsü ve sohbet geçmişi |
| `app/planner/`, `app/llm/` | Aday seçimi, puanlama, doğrulama, revizyon; Gemini/OpenAI ve kural tabanlı planlama |
| `app/workflow.py`, `app/scheduler/` | Yönetici onayı/yayınlama ve haftalık plan/tarif keşfi görevleri |
| `app/recipes/`, `data/recipes/` | Tarif içe aktarma, keşif, aday/onaylı tarif yönetimi ve örnek YAML tarifleri |
| `app/memory/`, `app/shopping/` | Kalıcı tercihler/geri bildirim; porsiyon, birim, kiler ve alışveriş hesapları |
| `app/db/` | SQLAlchemy modelleri, SQLite/PostgreSQL bağlantısı ve `create_all` ile ilk kurulum |
| `app/web_panel.py` | FastAPI paneli; token ile tarif görüntüleme, kalıcı kural ve porsiyon besin değeri düzenleme |
| `tests/` | pytest ile ajan, planlayıcı, alışveriş, güvenlik, kalıcılık ve panel kontrolleri |
| `requirements.txt`, `Dockerfile`, `docker-compose.yml` | Sabitlenmiş bağımlılıklar; Python 3.12 tabanlı konteyner; `data/` kalıcılığı |

`AGENT_PROVIDER` sohbet ajanını (Gemini/Anthropic), `LLM_PROVIDER` ayrı planlama/niyet katmanını seçer. Bunları birbirine karıştırmayın. Model adları ve ayar varsayılanları için `app/config.py` ile `.env.example` dosyasına bakın; sağlayıcıdaki güncel erişilebilirlik ve fiyatlar ayrıca doğrulanmalıdır.

Şema başlangıçta `create_all` ile kuruluyor; uygulanmış Alembic geçişleri yok. Şema değişikliğinde mevcut verinin taşınmasını ayrıca planlayın; bkz. [veritabanı notu](app/db/migrations/README.md).

## Ortak çalışma kuralları

1. İşe başlamadan `PROJE.md`, `DEVIR.md`, ilgili araç talimatları ve varsa çalışılan alt dizinin talimatlarını okuyun. `git status --short --branch` ve ilgili farkları inceleyin. Aynı çalışma kopyasında Claude ve Codex dönüşümlü çalışsın; diğer aracın bıraktığı değişiklikleri kendi değişikliğiniz saymayın.
2. Kullanıcının talebini küçük, doğrulanabilir işlere bölün. Mevcut değişiklikleri silmeyin, geri almayın veya ilgisiz dosyaları yeniden biçimlendirmeyin. Git dışında kalan dosyaları, sanal ortamı ve yerel veriyi koruyun.
3. Her tamamlanan küçük işten sonra, aracı değiştirmeden veya oturumu bitirmeden önce `DEVIR.md` dosyasını güncelleyin. Yarıda kalırsanız tamamlanan kısmı, kalan işi ve engeli yazın. Kalıcı mimari/çalıştırma kuralı değişirse `PROJE.md` veya asıl rehberdeki ilgili bölümü de güncelleyin.
4. Devir notuna tarih ve aracı, işin kapsamını, değişen dosyaları, kontrol komutlarını/sonuçlarını, yapılmayan kontrolleri ve somut sonraki adımı ekleyin. Doğrulanmış sonuçları, eski notlardan aktarılan iddiaları ve önerileri açıkça ayırın. Önceki açık işleri çözüldüğüne dair kanıt olmadan kapatmayın.
5. `.env`, anahtar/token değerleri, özel bağlantı bilgileri, kişisel Telegram kimlikleri ve gerçek kullanıcı verisini belgelere, çıktılara veya Git'e koymayın. Örneklerde yalnızca değişken adları/yer tutucular kullanın. Mevcut `.env` üzerine örnek dosya kopyalamayın.
6. Testlerde geçici veritabanı ve sahte dış servis istemcileri kullanın. Canlı botu veya zamanlayıcıyı doğrulama amacıyla başlatmayın; aynı token ile iki bot Telegram polling çakışmasına yol açabilir. Dış API'ye istek atan ve veritabanına yazan komutları sıradan testlerle karıştırmayın.
7. Yönetici onayı, aday tariflerin onaysız kullanılmaması, yayınlanmış planın korunması, haftalık işlemlerin tekrarlanabilirliği ve panel token kontrolü mevcut davranış sözleşmeleridir. Kural ve besin değeri yazma formlarında token/CSRF doğrulaması ve eski form denetimini koruyun. İlgili değişiklikleri mevcut testlerle doğrulayın.
8. Kullanıcının verdiği yetki sınırlarında ilerleyin. İlk ortak düzen kurulumu yalnızca belgelendirmeydi; sonraki istekte kalıcı yemek kurallarının ürün kodunda uygulanması yetkilendirildi. Canlı veriye müdahale, botu başlatma/durdurma ve dağıtım bu yerel geliştirme görevinin parçası değildir; sonraki görevlerin kapsamını kullanıcının yeni isteği belirler.

## Çalıştırma ve test

Proje kökünde çalışın. Python 3.12 konteynerde tanımlı sürümdür. Yerel kurulum ve Docker ayrıntıları README'nin “Local Run” ve “Run With Docker” bölümlerindedir.

Yeni bir ortam için temel sıra:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# Yalnızca .env henüz yoksa:
test -e .env || cp .env.example .env
# Gerekli ayarları .env içinde yerel olarak doldurduktan sonra:
python -m app.cli init-db
python -m app.cli import-recipes data/recipes
python -m app.cli run
```

Mevcut `.venv` varsa yeniden oluşturmadan önce durumunu kontrol edin. `init-db` ve içe aktarma veritabanına yazar; `run` Telegram, zamanlayıcı ve etkinse paneli başlatır. Bu komutlar ilk ortak çalışma kurulumu sırasında çalıştırılmadı.

Standart kontrol komutları:

```bash
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
```

`Settings` varsayılan olarak çalışma dizinindeki `.env` dosyasını okur; mevcut testlerin bazıları bu ayarları devralabilir. Bu nedenle kişisel `.env` ve canlı veritabanını içermeyen geçici bir kaynak kopyasında, temiz süreç ortamıyla test çalıştırmak uygundur. `app/`, `tests/` ve `data/recipes/` birlikte kopyalanmalıdır; bir test tarif dosyasını göreli yoldan açar. İlk doğrulamada kullanılan yöntem ve sonuç DEVIR.md içindedir.

`python -m app.cli check-agent` canlı sağlayıcıya istek gönderir; Gemini yolunda yapılandırılmış model zincirini dener ve kota tüketebilir. `plan-now` ve `discover-now` da veri yazabilir ve dış servis çağırabilir. Bunlar çevrimdışı test değildir.

README/CLOUD_DEPLOY içindeki operasyon ayrıntıları için güncel kod ve DEVIR.md'deki tutarsızlık notlarını kontrol edin. Belgede yazması, dağıtımın yapıldığını veya bir sağlayıcı/modelin bugün erişilebilir olduğunu kanıtlamaz.

## Kalıcı yemek kuralları (2026-10-15)

- Tek kayıt kaynağı `PreferenceService` / `preferences` tablosudur. Paneldeki
  “Yemek Kurallarım” ve Telegram komutları aynı kayıtları kullanır.
- `app/memory/rules.py` ortak yorumlama/denetim katmanıdır: yasak içerikler,
  öğün başına farklı yemek sayısı, kayıtlı kişi başı kalori sınırı, kalori
  gösterimi ve protein önceliği. Desteklenmeyen metin ajana iletilir, otomatik
  denetim sağlandığı iddia edilmez. Desteklenen yazımlar README'dedir.
- `app/recipes/nutrition.py` ve ayrı `recipe_nutrition` tablosu bir porsiyonun
  kalori/protein verisini, kaynağını ve tahmin durumunu tutar. Tablo eklenmesi
  `create_all` ile yapılır; mevcut tablolarda ALTER yoktur. Bilinmeyen değer
  sıfır değildir, değer uydurulmaz. Kurallar gerçek besin ölçümü garantisi değil,
  kayıtlı verilere dayalı yazılım denetimidir.
- Plan kaydetme, otomatik planlama, revizyon, onay ve yayınlama aynı kuralları
  denetler. Geçersiz revizyon kısmen kaydedilmez. Değişen kurallar yeni planlara
  uygulanır; mevcut menü otomatik değiştirilmez.
- İlgili regresyonlar `tests/test_meal_rules.py` içindedir. Şema ekleme, yeniden
  açılan oturum, form güvenliği, kuralların iki planlama yolunda uygulanması ve
  besin değeri düzenleme testlerini koruyun. Yeni bağımlılık eklenmedi.
