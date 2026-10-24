# WeeklyFoody — devir notu

Son güncelleme: **2026-10-15 — Claude**. Önce [PROJE.md](PROJE.md) dosyasını okuyun.

## Son tamamlanan iş (Claude, 2026-10-19): Foody Android uygulaması

Kullanıcı: "Bu Telegram'da olmuyor, app haline getir; Financia ve Cal-Track'i baz al."
Financia (`mtasci89/Financia`, `android/`) ve Cal-Track incelendi; Financia'nın yapısı,
teması, derleme ayarları, imza/CI düzeni ve **yalnızca INTERNET izni** kuralı alındı.
Fark: veri ve ajan sunucuda kaldı, uygulama HTTPS API'nin ince istemcisi.

- Sunucu: `app/api.py` (JSON API, bearer anahtar), `app/api_tls.py` (sertifika, SPKI pini,
  `FOODY1.` kodu, `.env` güncelleme), `app/main.py` API'yi TLS ile ayrı uvicorn sunucusunda
  başlatır (eksik ayar botu durdurmaz, günlüğe `app_api_not_started` yazar), CLI
  `uygulama-hazirla`, Telegram `/uygulama`. Ayarlar: `APP_API_*` (`.env.example`).
- Uygulama: `android/` (paket `com.foody`, ad "Foody"); ekranlar Menü, Alışveriş, Asistan,
  Tarifler (+detay), Kurallar, Ayarlar. Ayrıntı PROJE.md > Foody uygulaması.
- CI: `.github/workflows/uygulama.yml` (sözleşme + API testleri → Android testleri + APK →
  izin denetimi → `uygulama-son` sürümü).
- Kurulum betiği: `deploy/uygulama-ac.sh` (güncelle → anahtar/sertifika → firewalld 8443 →
  yeniden başlat → dışarıdan dene; ulaşılamazsa Oracle VCN kuralını tarif eder).

**Kontroller:** `pytest -q` → **274 geçti** (16 API + 11 sözleşme testi dahil); yerel HTTPS +
`curl --pinnedpubkey` (doğru pin 200, yanlış pin ve düz HTTP red); Android
`testDebugUnitTest` **21 geçti**; `assembleRelease` 3 MB imzalı APK, `aapt2` izinleri yalnızca
INTERNET (+ AndroidX iç izni); `CanliSunucuTest` gerçek Kotlin istemcisi ↔ gerçek Python HTTPS
API (3/3: veri okundu, yanlış pin ve yanlış anahtar reddedildi).

**Doğrulanmadı:** gerçek telefonda kurulum ve kullanım; Oracle'da 8443'ün dışarıya açık
olduğu (VCN kuralı kullanıcının işi olabilir); CI'nın GitHub'da ilk koşusu (push sonrası bakılacak).

**Durum (2026-10-24, kullanıcının çıktısıyla doğrulandı):** `./deploy/uygulama-ac.sh` çalıştı:
anahtar ve sertifika üretildi, firewalld'da 8443 açık, `app_api_started host=0.0.0.0 port=8443`,
sunucu içinden istek 401 (beklenen). Mac'ten internet üzerinden istek **000 (ulaşılamadı)**:
Oracle VCN güvenlik listesinde (ya da NSG'de) 8443 giriş kuralı eksik; kullanıcı ekleyecek.
Kullanıcı kuralı ekledi ve dışarıdan erişimin çalıştığını bildirdi ("oldu"). Telefonda APK
kurulumu ve `/uygulama` ile bağlanma henüz doğrulanmadı.

**Sıradaki adım:** kullanıcı Mac'te `git pull` → `./deploy/uygulama-ac.sh`; gerekirse Oracle
VCN'de 8443 giriş kuralı; GitHub Releases'tan `foody.apk` kur; Telegram `/uygulama` kodunu
Ayarlar'a yapıştır.

## Son tamamlanan iş (Claude + kullanıcı, 2026-10-15): bot Oracle sunucusuna taşındı

**Doğrulandı (kullanıcının çalıştırdığı komut çıktılarıyla):** `@weeklyfoodybot`
artık Oracle sunucusunda çalışıyor; Mac'teki bot kapatıldı ve **bir daha
başlatılmamalı** (aynı anahtarla iki polling çakışır).

- Sunucu: Oracle Linux 9.8, 1 GB RAM, SELinux **Enforcing**. Kullanıcı `opc`,
  bağlantı bilgisi README'deki SSH tüneli satırında. Kod
  `/home/opc/WeeklyFoody`, dal `claude/weeklyfood-bot-review-08wbec` (upstream
  izli), Python 3.11 sanal ortamı `.venv`.
- Servis: `weeklyfoody.service`; ek ayar
  `/etc/systemd/system/weeklyfoody.service.d/override.conf` →
  `ExecStart=/home/opc/WeeklyFoody/.venv/bin/python -m app.cli run`,
  `Restart=always`, `RestartSec=15`; `enable` edildi (sunucu açılınca başlar).
- **SELinux tuzağı:** servis ev klasöründeki `.venv/bin/python`'u `203/EXEC
  Permission denied` ile çalıştıramadı. Çözüm: `sudo chcon -R -h -t bin_t
  .venv/bin`. `chcon` kalıcı değildir; `.venv` yeniden kurulursa ya da sistem
  yeniden etiketlenirse tekrar gerekir (güncelleme betiği her seferinde yapar).
- Veri: Mac'teki `.env` ve `data/mealplanner.db` kopyalandı. Sunucunun eski
  verisi (eski bot `@lez_zet_bot`, 180 tarif) ve eski `.env`:
  `~/yedek-20261015-1358/` (sunucuda). Eski `.venv` `.venv.eski-*` olarak duruyor.
- `check-agent` (14:02): `gemini-3.8-flash` KOTA DOLU, `3.5-flash-lite` ve
  `3.1-flash-lite` çalışıyor; bot yedekle cevap veriyor.
- Web paneli açık ama yalnızca `127.0.0.1:8000`; erişim SSH tüneliyle (README).
- İkinci "Scheduler started" satırı python-telegram-bot JobQueue'sunun boş
  zamanlayıcısı; görevler tek kez çalışır.
- **Güncelleme:** Mac'te `./deploy/sunucu-guncelle.sh` (DB yedeği →
  `git pull --ff-only` → pip → `chcon` → restart → durum). Günlük:
  `./deploy/sunucu-gunluk.sh [satır]`. Yedekler `~/yedekler/`, 30 günden eskisi silinir.

**Açık işler:** dal `main`'e birleştirilince sunucu `main`'e geçirilmeli;
düzenli (günlük) DB yedeği yok, yalnızca güncellemede alınıyor; Telegram ve
Gemini anahtarlarının yenilendiği doğrulanmadı.

## Son tamamlanan iş (Claude, 2026-10-15): kalori, alışveriş listesi, yeni tarifler

- **Sorun (kullanıcı ekran görüntüsü):** "kalorileri yaz, kural olarak ekle"
  isteğine ajan (büyük ihtimalle yedek model) **ters** kural ekledi: "Her akşam
  bir kişinin toplam kalorisi yazılmasın". Kalori hiç gösterilmedi; tariflerde
  değer de yoktu. Kullanıcının DB'sinde bu yanlış kural duruyor; kullanıcı
  `/kural_sil` ile silmeli.
- **Kural tanıma (`app/memory/rules.py`):** serbest "kalori ... yaz/göster"
  yazımları gösterim kuralı (olumsuzlar hariç); "Bir kişi için bir öğün 1000
  kaloriyi geçmesin" ve "Her akşam 3 farklı yemek olsun" artık denetlenen kural.
- **Otomatik tahmin (`app/agent/nutrition.py`):** `NutritionEstimator` eksik
  kalori/proteini tek JSON istekle (`GeminiBackend.generate_json`, model
  zinciriyle) tahmin eder, `estimated=True` kaydeder, elle girileni ezmez.
  Ajan araçları (`plan_kaydet`, `ogun_degistir`, `plani_getir`), `/menu`,
  `/regenerate` ve haftalık plan kural varsa bunu çağırır (`fill_for_rules`;
  kalori sınırı varsa otomatik planlayıcı için tüm kütüphane).
- **Özeti sistem ekler:** ajan turu planı okuduysa/değiştirdiyse
  (`AgentReply.plan_session_id`) ve gösterim kuralı varsa `calorie_summary`
  cevabın altına eklenir (`app/bot/handlers.py::_agent_turn`).
- **Alışveriş listesi:** miktarlar alınabilir değere yukarı yuvarlanır (350 g,
  1 adet, 1,5 yemek kaşığı; ondalık virgül), miktarsız tekrarlar düşer,
  kategori kelime başında eşleşir (ketçap artık "Et" değil) ve her seferinde
  güncel kuralla hesaplanır. `tarif_detay` kişi sayısına göre ölçekler.
- **Yeni tarifler:** istem artık ajanın önerdiği her kütüphane dışı yemeği aynı
  turda `tarif_ekle` ile aday kaydetmesini, kullanıcı beğenince
  `tarif_onayla` ile onaylamasını ister; kuralı tersine çevirmeyi açıkça yasaklar.
- Testler: `pytest -q` → **246 geçti**. Canlı Gemini ile denenmedi.

## Son tamamlanan iş (Claude, 2026-10-15): zaman aşımı ve web'de tarif keşfi

- **Sorun (kullanıcı logu):** "haftalık yemek listesi oluştur" turu
  `gemini-3.8-flash`'ta 90 sn bekleyip `504 DEADLINE_EXCEEDED` aldı; SDK aynı
  modeli 504'te tekrar denediği için bir 90 sn daha gidiyordu → tur zaman aşımı.
- **Düzeltme (`app/agent/gemini_backend.py`, `app/config.py`):** SDK artık
  yalnızca 500'ü tekrar dener (504 zincirde sonraki modele geçer); meşgul/zaman
  aşımı/kota veren model `COOLDOWN_SECONDS` boyunca **sonraki turların başında**
  atlanır (tur ortasında model değiştirilmez: `ModelCursor.started`); istek
  zaman aşımı 90 → 60 sn.
- **Keşif artık web'de:** `/discover <konu>`, haftalık zamanlanmış keşif ve
  `python -m app.cli discover-now` ajan + web araması (`discovery_prompt`)
  kullanıyor; bulunanlar kaynağıyla ADAY kaydedilir. Ajan yoksa eski
  (modelden fikir isteyen) yol çalışır. Haftalık sonuç yöneticinin sohbet
  geçmişine düşer, "şunu onayla" diye cevap verilebilir.
- Testler: `pytest -q` → **218 geçti**; `pyflakes` temiz.
  Canlı Gemini ile denenmedi.

## Son tamamlanan iş (Claude): iki kural çalışmasının birleştirilmesi

Aynı istek ("kurallarımı bir yerde yazayım") Claude ve Codex tarafından paralel
ve farklı biçimde yapılmıştı. `codex/telegram-rules` dalı
`claude/weeklyfood-bot-review-08wbec` dalına birleştirildi; tek kayıt kaynağı
Codex'in tasarımı oldu:

- **Kurallar:** yalnızca `preferences` tablosu + `app/memory/rules.py`
  (`MealRules`). Claude'un ayrı `house_rules` tablosu/belgesi kaldırıldı.
  `app/agent/rules.py` artık yalnızca Telegram komutları ve ajan araçları için
  `PreferenceService` üzerine ince bir giriş (`HouseRules`).
- **Besin değeri:** yalnızca `recipe_nutrition` tablosu. Claude'un
  `recipes.calories_per_serving/protein_g_per_serving` sütunları ve
  `ensure_columns` kaldırıldı (hiçbir canlı ortama gitmemişti).
- **Telegram (modelsiz):** `/kurallar` (liste + sistemin neyi denetlediği),
  `/kural_ekle`, `/kural_sil <no|ifade>`, `/kurallari_yaz` (tüm listeyi yaz;
  geçersiz/çelişen girişte liste değişmez).
- **Ajan araçları:** `kurallari_goster`, `kural_ekle`, `kural_sil`,
  `besin_degeri_kaydet`. Son araç eksik değerleri `estimated=True`,
  kaynak "ajan tahmini" olarak yazar; `estimated=False` (elle girilmiş) kaydın
  üzerine yazmaz. Codex isteminin "eksik sayıları tahmin etme" kuralı bu
  araçla değiştirildi: tahmin serbest ama tahmin olarak işaretli.
- **Davranış değişikliği:** yemek sayısı kuralında ajan planında (ve onayda)
  tamamen boş gün serbest ("pazar dışarıdayız"); yazılan her öğün kurala uymak
  zorunda. Otomatik planlayıcı yine her günü doldurur (`PlanValidator`).
  Kullanıcı daha önce "sistem izin vermiyor" katılığından şikâyet etmişti.
- `PreferenceService.delete("")` artık hiçbir şey silmiyor (önce en yeni
  kuralı sessizce pasifleştiriyordu).
- Kontrol: `pytest -q` → **213 geçti**; `pyflakes app tests` temiz
  (`tests/test_meal_rules.py`deki bilinçli `toolset` fikstür içe aktarımı hariç).
  Canlı Telegram/Gemini ve Oracle sunucusu bu işte denenmedi.

## Sıradaki adım

1. Kullanıcı Mac'te bu dalı çekmeli. Yerelde commit edilmemiş Codex
   değişiklikleri artık bu dalda; `dist/` Git dışında bırakıldı (Python
   uygulamasıyla ilişkisi yok, eski React derlemesi gibi görünüyor).
2. Oracle sunucusuna dağıtım: veritabanı yedeği → dalı çek →
   `pip install -r requirements.txt` → `.env` Gemini ayarları → servisi yeniden
   başlat → `python -m app.cli check-agent`. Aynı bot anahtarıyla Mac'teki bot
   kapatılmalı.
3. **Doğrulandı (kullanıcı, 2026-10-15):** kullanıcının telefonda kullandığı tek
   bot `@weeklyfoodybot` ve **Mac'te** çalışıyor (Mac'teki bot durunca cevap
   vermiyor). Oracle sunucusundaki eski kurulum başka bir bot anahtarı
   kullanıyor. Karar: `@weeklyfoodybot` sunucuya taşınacak; sunucu `.env`'deki
   Telegram anahtarı Mac'teki anahtarla değiştirilecek (değer gösterilmeden).
   Kullanıcının BotFather'da iki botu var: `@weeklyfoodybot` (WeeklyFoody) ve
   `@lez_zet_bot` (Lez). Sunucudaki eski kurulumun `@lez_zet_bot` olduğu
   kullanıcının tahmini — **doğrulanmadı** (sunucuda getMe ile kontrol edilmeli).
   `@lez_zet_bot` 26 Ağustos'taki ve 15 Ekim'deki `/start`'a hiç cevap vermedi:
   sunucudaki servis bu anahtarla çalışmıyor ya da hata veriyor. Sunucuda
   servis durumu ve günlüğü incelenmeli; plan değişmez (sunucuya
   `@weeklyfoodybot` anahtarı konacak).
   **Karar (kullanıcı):** Mac'teki bot ve verisi esas; sunucuya Mac'teki
   veritabanı taşınacak. Sunucudaki 180 tarif yalnızca başlangıç yönelimi —
   yedeklenip saklanacak, gerekirse sonra ayrıca içe aktarılır. Sıra: önce Mac
   birleşik dalda denenir, sonra aynı kod + Mac `.env` + Mac veritabanı sunucuya. Sunucu bot başladıktan sonra Mac'teki bot kalıcı kapatılmalı
   (aynı anahtarla iki bot polling çakışması yapar).

---

## Önceki iş (Codex)

Kullanıcının “kurallarımı bir yerde yazayım ve her seferinde tekrar söylemeyeyim”
talebi uygulandı. Ortak çalışma düzeni önceki işte kurulmuştu; kullanıcı bu
sonraki işte ürün kodu geliştirmesini açıkça yetkilendirdi. Claude ile devam
edebilmek için mevcut servisler genişletildi, yeni bağımlılık eklenmedi.

Tamamlanan küçük işler:

1. **Kalıcı kurallar:** mevcut `preferences` tablosu üzerinde metin editörü,
   güncelleme/silme, eski form kontrolü ve ortak yorumlama/denetim katmanı.
2. **Menüye uygulama:** otomatik planlama, ajan araçları, revizyon, onay ve
   yayınlama aynı yasak/yemek sayısı/kalori kurallarını denetliyor. Geçersiz
   revizyonun kısmen kaydedilmesi engellendi. Ajan bağlamı her turda kayıtlı
   kuralları okuyor; tanınmayan metin için otomatik denetim varmış gibi davranmıyor.
3. **Besin değerleri:** porsiyon başına kalori/protein, kaynak ve tahmin durumu;
   panelden düzenleme, YAML/JSON içe aktarma, menüde gösterim ve öğün toplamı.
   Kalori sınırında eksik veri açık hata oluşturuyor. Protein isteği aday
   puanını etkiliyor. Uzayan Telegram menüleri parçalara ayrılıyor.
4. **Kontroller ve devir:** 31 yeni regresyon testi, toplam 193 başarılı test;
   örnek verilerle tarayıcıda masaüstü görünümü incelendi. Kullanım ve şema
   davranışı README, PROJE ve veritabanı notuna işlendi.

Bu özellik yerel kaynakta hazırdır. **Canlı bot yeniden başlatılmadı, kişisel
`.env`/veritabanı değiştirilmedi, kullanıcı adına kural etkinleştirilmedi,
commit/push/dağıtım yapılmadı.** Geçici test/önizleme verileri gerçek veriler değildir.

## Kullanıcı deneyimi ve kapsam

- Panelde **Yemek Kurallarım** (`/preferences`): her satıra bir kural;
  satır düzenleme/değiştirme/silme. Telegram tercih komutları aynı kayıtları kullanır.
- Desteklenen örnekler: `Balık kullanma`, `Her öğünde 3 farklı yemek olsun`,
  `Kalorilerini de yaz yanına`, `Kişi başı öğün en fazla 1000 kcal`,
  `Protein ağırlıklı olsun`. Bunlar canlı tercihlere yazılmadı.
- “3 farklı yemek” için kapsam soruldu; ek yanıt gelmediği için başlangıçta
  belirtilen **her öğünde üç farklı tarif** varsayımı uygulandı ve panelde
  açıklandı. Otomatik şablon üç yemekte ana + meze/salata + yan; sayı 1–6.
- Kayıtlı kesin kurallar ajanın esnek gün şeklinden önceliklidir. Sayı kuralı
  varken yapılandırılmış her gün/öğünde sayı denetlenir; istisna için kural
  düzenlenmelidir. Önceden var olan taslak kendiliğinden değişmez; yeni kurala
  aykırıysa onay/yayın engellenir.
- `Tercih:` öneki yumuşak tercih olarak korunur. Genel doğal dilin tamamı
  otomatik kısıta çevrilmez; tanınmayan kurallar saklanır ve “yalnızca ajana
  iletilir, otomatik denetim yok” olarak gösterilir. Balık türleri ve yaygın
  Türkçe ekler desteklenir; sınırsız bir gıda ontolojisi yoktur.
- Kalori sınırı her yemekten bir porsiyonun **kişi başı** toplamıdır; aile kişi
  sayısıyla çarpılmaz. Kaynak/tahmin durumu korunur. Eksik veri sıfır değildir;
  değerler uydurulmaz. Kontrol kayıtlı değerlere dayanır, gerçek besin ölçümü
  garantisi değildir. Protein gramı yoksa yalnızca kaynak türüyle nitel puan
  verilir; sayısal protein hedefi sağlandığı iddia edilmez.
- Kalori/yemek sayısı için kural tabanlı yedek planlayıcı aday havuzunda sınırlı
  arama yapar; çözüm bulamazsa veya arama sınırına ulaşırsa açık hata döner.
- Panel varsayılan olarak hâlâ kapalıdır; mevcut panel ayarları geçerlidir.
  Panel token'ı artık kural ve besin değeri yazma yetkisi de verir. Formlar
  token/CSRF doğrulaması ve eski form kontrolü içerir; özel yanıtlar önbelleğe alınmaz.

## Değişen dosyalar

| Alan | Dosyalar |
| --- | --- |
| Ortak kurallar | `app/memory/rules.py` (yeni), `app/memory/preferences.py` |
| Besin değeri kaydı | `app/recipes/nutrition.py` (yeni), `app/db/models.py`, `app/recipes/importer.py`, `app/recipes/service.py` |
| Planlama/denetim | `app/planner/candidate_selector.py`, `scorer.py`, `validator.py`, `service.py`, `revision.py`; `app/llm/rule_based.py` |
| Ajan ve kullanıcı akışı | `app/agent/tools.py`, `app/agent/prompts.py`, `app/bot/handlers.py`, `app/formatting.py`, `app/scheduler/weekly.py`, `app/workflow.py` |
| İşlem bütünlüğü | `app/memory/feedback.py` (revizyonda tek işlem için isteğe bağlı commit) |
| Panel | `app/web_panel.py` |
| Test | `tests/test_meal_rules.py` (yeni; mevcut sahte araç test sınırını kullanır) |
| Belgeler | `README.md`, `CLOUD_DEPLOY.md`, `app/db/migrations/README.md`, `PROJE.md`, `DEVIR.md` |

`AGENTS.md` ve `CLAUDE.md` önceki kurulumdaki gibi korundu: ikisi de PROJE/DEVIR
okunmasını ve her küçük iş sonunda DEVIR güncellenmesini ister.

## Veri ve sürüm uyumluluğu

`recipe_nutrition` ayrı bir tablodur; `init-db` veya normal uygulama başlangıcı
`create_all` ile ekler. Eski tarif/tercih tablolarında ALTER veya veri silme yok.
Eski şemadan geçiş ve tekrarlı `init-db` SQLite üzerinde test edildi; canlı
PostgreSQL geçişi yapılmadı. Güncellemede normal yedekleme sürecini izleyin.

Besin değeri içermeyen eski YAML/JSON dosyalarını tekrar içe aktarmak mevcut
besin değerini silmez; açık `nutrition: null` siler. Kural silme mevcut
tercih kaydını pasifleştirir. İkinci bir Markdown/JSON kural deposu oluşturulmadı.

## Git ve korunmuş mevcut durum

- Proje: `/Users/mustafa/Documents/GitHub/WeeklyFoody`.
- Dal: `claude/weeklyfood-bot-review-08wbec`; başlangıç HEAD: `3386833`.
- Bu iş başlarken izlenen ürün dosyaları temizdi; önceki işten dört ortak
  Markdown belgesi ve altı `dist/` dosyası Git dışında bulunuyordu.
- `dist/index.html`, `favicon.ico`, `placeholder.svg`, `robots.txt`,
  `dist/assets/index-DDE2pgO5.css`, `dist/assets/index-DzVAM6UF.js` korundu.
  Bu dosyaların Python uygulamasıyla ilişkisi hâlâ doğrulanmadı.
- Önceki belgeler korundu/güncellendi; değişiklikler commit edilmemiştir.
  Fetch yapılmadı; ilk incelemede yerel upstream farkı `0/0` idi, uzak
  sunucunun şu anki durumu doğrulanmadı.

## Kontroller

Kişisel `.env` ve veritabanı içermeyen `/private/tmp/weeklyfoody-rules-work`
kopyasında mevcut sanal ortamın Python 3.12.10'u kullanıldı. Geçici test ve
önizleme yardımcıları projeye eklenmedi. Tekrarlamak için `app/`, `tests/` ve
`data/recipes/` klasörlerini temiz geçici dizine kopyalayıp oradan çalıştırın:

```bash
/usr/bin/env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 \
  /Users/mustafa/Documents/GitHub/WeeklyFoody/.venv/bin/python \
  -m pytest -q -p no:cacheprovider
```

- Son tam test: **193 geçti**, 21,67 saniye, **15.809 uyarı**.
- 31 yeni test: kayıt/restart, ekleme/düzenleme/silme, çelişki ve eski form,
  yasak türler/ekler, ajan ve otomatik plan, kalori/çeşit sınırları, eksik veri,
  modelden geçersiz çıktı sonrası yedek plan, revizyon geri alma, onay/yayın,
  token/CSRF/HTML kaçışları, besin değeri içe aktarma ve eski şema uyumluluğu.
- Önceki 162 test de geçiyor. Bağımlılıklar değiştirilmedi; önceki işte
  `pip check` başarılıydı ve kurulu sürümler requirements.txt ile eşleşmişti.
- Örnek verili panel HTML'i yerel Chrome ile çizildi; masaüstü görünümü
  incelendi. Form kaydetme/düzenleme HTTP testleri TestClient ile doğrulandı.
- Kaynak sözdizimi, belge bağlantıları ve değişiklik kapsamı kontrol edildi.

Mevcut uyarılar devam ediyor: `datetime.utcnow()` kullanımdan kaldırma uyarıları,
dört Gemini testindeki `BaseApiClient.aclose` await uyarısı, başlangıçtaki
pytest-asyncio fixture loop scope uyarısı. Bunlar bu özellikte çözülmedi.

## Açık işler / doğrulanmayanlar

Canlı Telegram/LLM akışı, API kota/model erişimi, gerçek verilerin besin değeri
kalitesi, canlı PostgreSQL, Docker derlemesi ve gerçek mobil tarayıcı henüz
doğrulanmadı. Kullanıcıya verilen örnekler gerçek kalori verisi olarak eklenmedi.

Önceki bakım işleri açık kalıyor: README'deki yalnızca Anthropic anahtarıyla
çalışma ifadesi, 1 saat/5 dakika önbellek çelişkisi, `check-agent` için tek
istek açıklaması ve keşfin etkinliği açıklaması. İlgisiz model/fiyat iddiaları
bu görevde canlı doğrulanmadı. Test uyarıları ve `dist/` incelemesi ayrı işler.

## Claude veya Codex ile sıradaki adım

Özellik yerelde tamamlandı. Kullanıcı botun Mac üzerinde açık bir terminalde
çalıştığını doğruladı ve güncelleme komutlarını kendisi çalıştırmak istedi.
Gizli değerler gösterilmeden yapılan ayar kontrolünde SQLite
`data/mealplanner.db`, kapalı panel, `127.0.0.1:8000` ve henüz tanımlanmamış
panel token'ı görüldü. Terminalde eski botu Ctrl+C ile durdurma, SQLite
backup API ile yedek alma, `init-db`, mevcut `.env` değerlerini koruyarak
paneli/token'ı yapılandırma ve tek bot örneğini başlatma komutları hazırlanıyor.
Bu adımların kullanıcı tarafından çalıştırıldığı henüz doğrulanmadı; canlı
güncelleme tamamlandı diye işaretlemeyin. Panelde gerçek kuralları kullanıcı
seçsin; kalori sınırından önce tariflerin porsiyon bilgileri tamamlansın.

Canlı kabul akışı: bir kural kaydet → yeni konuşmada menü oluştur → aynı kuralın
uygulandığını gör → kuralı değiştir/sil → yeni taslakta etkisini doğrula. Kalori
verisi eksik tarif için açık hata ve bilgisi tamamlanmış öğünde toplamı ayrıca
kontrol edin. Canlı doğrulama tamamlanmadan yapıldı diye yazmayın.

Her küçük iş sonunda bu notu güncelleyin; açık bakım işlerini ve doğrulanmayan
noktaları kanıt olmadan kapatmayın. Değişiklikleri incelemeden reset/temizlik
veya geniş kapsamlı yeniden yazma yapmayın.
