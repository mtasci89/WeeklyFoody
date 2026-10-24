# WeeklyFoody — ortak proje rehberi

Bu dosya Claude ve Codex için kalıcı proje bağlamıdır. Güncel durum, son kontroller ve sıradaki iş [DEVIR.md](DEVIR.md) içinde tutulur. Her oturumda ikisini de okuyun. Ayrıntılı kullanım ve kurulum anlatımı [README.md](README.md), mevcut bulut kurulum rehberi [CLOUD_DEPLOY.md](CLOUD_DEPLOY.md) içindedir; aynı bilgileri burada tekrar çoğaltmayın.

## Amaç ve kapsam

WeeklyFoody, kişisel/aile kullanımı için haftalık yemek planlayan bir Python uygulamasıdır. Yönetici arayüzü Foody Android uygulamasıdır (`android/`); Telegram botu alıcılara gönderim, bildirim ve bağlantı kodu için çalışmaya devam eder. Yöneticiyle Türkçe revizyon yapar; onaylanan menüyü ve birleştirilmiş alışveriş listesini yapılandırılmış alıcılara gönderir. Tarifler, tercihler, geri bildirimler ve haftalık iş akışı SQLAlchemy veritabanında saklanır.

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
| `app/api.py`, `app/api_tls.py` | Foody uygulamasının HTTPS JSON API'si (bearer anahtar), kendinden imzalı sertifika, SPKI pini ve `FOODY1.` bağlantı kodu |
| `android/` | Foody Android uygulaması (Kotlin/Compose, paket `com.foody`); aşağıdaki "Foody uygulaması" bölümü |
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
7. Yönetici onayı, aday tariflerin onaysız olarak otomatik seçim havuzuna girmemesi (2026-10-24'ten beri adaylar menüye "yeni yemek" olarak konabilir; bkz. Haftalık yeni yemekler), yayınlanmış planın korunması, haftalık işlemlerin tekrarlanabilirliği ve panel token kontrolü mevcut davranış sözleşmeleridir. Kural ve besin değeri yazma formlarında token/CSRF doğrulaması ve eski form denetimini koruyun. İlgili değişiklikleri mevcut testlerle doğrulayın.
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
  “Yemek Kurallarım”, Telegram komutları (`/kurallar`, `/kural_ekle`,
  `/kural_sil`, `/kurallari_yaz`) ve ajan araçları (`kural_ekle` vb.,
  `app/agent/rules.py` üzerinden) aynı kayıtları kullanır. İkinci bir kural
  deposu açmayın.
- `app/memory/rules.py` ortak yorumlama/denetim katmanıdır: yasak içerikler,
  öğün başına farklı yemek sayısı, kayıtlı kişi başı kalori sınırı, kalori
  gösterimi ve protein önceliği. Desteklenmeyen metin ajana iletilir, otomatik
  denetim sağlandığı iddia edilmez. Desteklenen yazımlar README'dedir.
- `app/recipes/nutrition.py` ve ayrı `recipe_nutrition` tablosu bir porsiyonun
  kalori/protein verisini, kaynağını ve tahmin durumunu tutar. Tablo eklenmesi
  `create_all` ile yapılır; mevcut tablolarda ALTER yoktur. Bilinmeyen değer
  sıfır değildir. Ajan eksik değerleri `besin_degeri_kaydet` ile
  yalnızca `estimated=True` olarak tahmin edebilir; elle girilmiş değerin üzerine yazmaz. Kurallar gerçek besin ölçümü garantisi değil,
  kayıtlı verilere dayalı yazılım denetimidir.
- Plan kaydetme, otomatik planlama, revizyon, onay ve yayınlama aynı kuralları
  denetler. Ajan planında tamamen boş bırakılan gün yemek sayısı kuralını
  ihlal etmez; otomatik planlayıcı her günü doldurur. Geçersiz revizyon kısmen kaydedilmez. Değişen kurallar yeni planlara
  uygulanır; mevcut menü otomatik değiştirilmez.
- İlgili regresyonlar `tests/test_meal_rules.py` içindedir. Şema ekleme, yeniden
  açılan oturum, form güvenliği, kuralların iki planlama yolunda uygulanması ve
  besin değeri düzenleme testlerini koruyun. Yeni bağımlılık eklenmedi.

## Canlı ortam (2026-10-15)

Bot Oracle sunucusunda `weeklyfoody.service` olarak çalışır; Mac'te
`app.cli run` başlatmayın. Sunucu telefondan güncellenebilir: Telegram `/guncelle`
ya da uygulama Ayarlar → "Sunucuyu güncelle" → `app/updater.py` →
`sudo -n systemd-run --uid=opc ... /bin/bash deploy/kendini-guncelle.sh` (botun dışında;
SELinux yüzünden betik `/bin/bash` ile okunur). İşaret dosyası `data/guncelleme.json`;
yeni bot açılışta sonucu yöneticiye yazar, hata olursa betik `app.cli bildir` ile bildirir
ve servisi yeniden başlatmaz. `opc` kullanıcısının parolasız sudo'su gerekir (OCI varsayılanı). Güncelleme ve günlük için `deploy/` altındaki
betikler; ayrıntı ve SELinux notu DEVIR.md'de.

## Haftalık yeni yemekler (2026-10-24)

Kullanıcı isteği: menü her hafta otomatik gelsin, kütüphanenin dışına çıksın; "x, y, z
olmamış, daha yenilikçi şeyler koy" deyince asistan hem tariflere hem internetteki
sıradışı tariflere baksın, ev kurallarına uysun.

- "Yeni yemek" = aday (`candidate`) tarif. `plan_kaydet`/`ogun_degistir` adayları kabul
  eder (pasifleri değil); menü JSON'unda `yeni: true`, Telegram'da "✨ yeni". Menüyü
  onaylamak adayı onaylamaz; aile beğenirse `tarif_onayla`/"Listeye ekle" ile kalıcı
  listeye (otomatik seçim havuzuna) geçer.
- Sayı: `WEEKLY_NEW_DISHES` (varsayılan 2, 0-7); ev kuralı ezer: "her hafta 3 sıradışı
  yemek olsun", "yeni yemek ekleme" → 0 (`MealRules.new_dishes`, `parse_new_dishes`).
- Otomatik akış: cumartesi keşfi (ajan, web) aday ekler → pazar `create_or_get_weekly_session`
  denenmemiş adayları rolüne uygun öğünlere, farklı günlere, kurallara aykırı düşmeden koyar
  (`app/planner/novelty.py`) → yine eksikse ve ajan açıksa `weekly_plan_job` ajana
  `weekly_novelty_prompt` ile internetten bulup ekletir (menüyü onaylamaz).
- Sohbet akışı: istemde "Bunlar olmamış, daha yenilikçi bir şey koy" bölümü (kütüphane +
  zorunlu web araması, kural denetimi, `tarif_ekle` + `ogun_degistir`, gerekçe kaydı).
  `plan_hazirla` hedef sayıyı ve denenmemiş adayları verir; `plan_kaydet` eksikse uyarır.

## Haftalık meze listesi ve menü düzenleme (2026-10-24, uygulama 1.5)

Kullanıcı: "mezeleri öğünlere ekleme", "mezeler günlere bölünmesin"; asistan ön planda,
menü tek bakışta görünsün.

- Mezeler günlere bölünmez: plan öğesi slotu `hafta_meze_N`, tarihi haftanın ilk günü
  (`config.WEEKLY_BASE`, `is_weekly_slot`). Hiçbir öğüne sayılmaz (kalori, yemek sayısı),
  alışverişe bir kez girer. Sayı `WEEKLY_MEZE_COUNT` (varsayılan 4; 0 = eski, her güne);
  ev kuralı ezer: "mezeler günlere bölünmesin", "haftada 3 meze", "mezeler günlere
  dağıtılsın" (`parse_weekly_mezes`). Bu kipte günlük şekilden meze rolü çıkar
  (`settings_for_plan`); otomatik plan listeyi `app/planner/mezes.py` ile doldurur.
- Ajan araçları: `ogun_ekle` / `ogun_cikar` (haftayı baştan yazmadan), `ogun_degistir`
  tarih="HAFTA" ve `hafta` parametresi; tarih verilirse o tarihin haftası seçilir
  (eskiden hep "aktif" hafta değişiyordu). `plan_kaydet` "HAFTA|hafta_meze_1|Ad" alır,
  günlük meze satırını reddeder.
- API: menü JSON'unda `plan.mezeler`; `POST /menu/ekle`, `/menu/cikar`; `/menu/degistir`
  `hafta` alır. Sohbet cevabında `menu` ve `degisiklikler` (tur öncesi/sonrası farkı);
  uygulama kanalında ajana "menüyü metin olarak tekrar yazma" denir (`channel="uygulama"`).
- Uygulama 1.5: Asistan ana ekran (sohbet + menü kartı), Menü sekmesi tek bakışta tablo.
  Testlerde `GORUNTU=<klasör>` ile `GoruntuTest` ekran görüntüsü alır.
- Testlerin çoğu eski "her güne meze" varsayımıyla yazıldığı için `tests/conftest.py`
  `weekly_meze_count=0` kullanır; yeni davranış `tests/test_weekly_mezes.py`'de.

## Foody uygulaması (android/, 2026-10-19)

Mimari: Financia/Cal-Track tarzı yerel Android uygulaması, ama veri ve zekâ sunucuda.
Uygulama yalnızca ince istemcidir: `app/api.py`'deki `/api/v1/*` uçlarını çağırır
(menü, onay, öğün değiştirme, tarifler + aday onayla/çıkar, alışveriş, kurallar,
sohbet + en fazla 4 görsel, web'de keşif). 1.4'ten beri asistan ayrı sekme değil, Menü
ekranının altında: yemekler seçilir ("Daha yenilikçi bir şey koy"), son cevap menünün
altında, istenirse tüm sohbet açılır. Asistan her şeyi yapabilir: ek olarak
`menuyu_onayla` (yalnızca açık istekle) ve `kiler` araçları var. Gemini anahtarı telefonda değil sunucuda. Telefonda yalnızca
adres + uygulama anahtarı + sertifika pini (EncryptedSharedPreferences) ve alışveriş
işaretleri (düz SharedPreferences, hafta başına) durur.

- **Bağlantı:** `python -m app.cli uygulama-hazirla --adres https://IP:8443` anahtarı
  (`APP_API_TOKEN`), sertifikayı (`data/foody-api.crt/.key`, git dışı) ve `.env`
  satırlarını üretir; Telegram `/uygulama` komutu `FOODY1.` kodunu yöneticiye yollar.
  Uygulama `SabitAnahtarGuveni` ile yalnızca pini tutan sertifikayı kabul eder.
- **Sözleşme:** API cevap biçimi `android/app/src/test/resources/ornek/*.json`
  örnekleriyle sabittir; örnekler `python -m tests.app_samples android/app/src/test/resources/ornek`
  ile gerçek API'den üretilir, `tests/test_app_contract.py` uyumu denetler. Bir alan
  adını değiştirirsen örnekleri yeniden üret ve Kotlin modellerini (`data/Modeller.kt`) uyumla.
- **İzin kuralı (Financia ile aynı, banka uygulamalarıyla uyum):** yalnızca `INTERNET`.
  Fotoğraf ekleme izin istemeden yapılır: galeri için sistem fotoğraf seçicisi
  (`PickMultipleVisualMedia`), kamera için telefonun kamera uygulaması (`TakePicture`)
  ve dışa kapalı bir `FileProvider` (yalnızca `cache/kamera/`). `CAMERA` ya da depolama
  izni EKLENMEZ: manifestte `CAMERA` olursa kamera uygulamasını çağırmak da izin ister.
  Kamera, bildirim, erişilebilirlik, açılışta başlama vb. eklenmez; CI izin listesini denetler.
- **Test:** `cd android && ./gradlew :app:testDebugUnitTest` (modeller, bağlantı kodu,
  pin, Robolectric ekranları). `CanliSunucuTest` yalnızca `FOODY_CANLI_KOD` verilirse
  gerçek sunucuya bağlanır. Robolectric'te AlertDialog içindeki metin alanı hiç
  durulmuyor (AppNotIdle); pencere içeriklerini ayrı composable yapıp pencere olmadan test edin.
- **Derleme/yayın:** `.github/workflows/uygulama.yml` → `uygulama-son` sürümünde
  `foody.apk`. İmza anahtarı `android/app/release.keystore` (şifre `foodyapp`) bilerek
  depoda: aynı anahtarla yeni APK eskisinin üzerine kurulur. Depo herkese açık olduğu
  için depoyu özel yapmak önerilir (kullanıcıya söylendi).
- Sunucuda 8443 hem `firewalld`'da hem Oracle VCN güvenlik listesinde açık olmalı
  (`deploy/uygulama-ac.sh`).
