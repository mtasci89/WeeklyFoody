# WeeklyFoody — devir notu

Son güncelleme: **2026-10-24 — Claude**. Önce [PROJE.md](PROJE.md) dosyasını okuyun.

## Son tamamlanan iş (Claude, 2026-10-25): boş tarifler tamamlanıyor

Kullanıcı ekran görüntüsü: Tarifler > Bu hafta'da bazı tarifler boş (Brokoli Çorbası,
Mercimek Çorbası, Fırında Püreli Tavuk). Sebep: kütüphanenin çoğu eski menü Excel'inden
yalnızca adlarıyla geldi (`HistoricalMenuExcelImporter`: "ingredients can be taught later");
bu tarifler alışveriş listesine de hiçbir şey eklemiyordu.
- `app/agent/recipe_fill.py` `fill_recipes`: malzemesi olmayan tarifleri 6'şarlı tek JSON
  isteğiyle (4 kişilik, miktarlı malzeme + 3-7 adım) tamamlar, not düşer; her tarif bir kez;
  eşzamanlı istekler kilitle sıraya girer. Çağrıldığı yerler: ajanın `_ensure_nutrition`'ı
  (menüye koyarken), API `/menu/tarifler`, `/alisveris`, `/tarifler/{id}`, `/menu/onayla`,
  pazar `weekly_plan_job`.
- Kontroller: pytest 373 geçti (`tests/test_recipe_fill.py`). Uygulama değişmedi (1.8).
- **Doğrulanmadı:** gerçek Gemini'nin ürettiği tariflerin kalitesi; ilk açılışta (çok boş
  tarif varsa) birkaç saniyelik gecikme.

## Son tamamlanan iş (Claude, 2026-10-25): yasak yerine düşünen model

Kullanıcı tekrar yasağına: "Kural değil, modelin bunu düşünmesini bekliyorum, böylesi çok
aptalca!" Değişiklik (yalnızca sunucu; uygulama 1.8 aynı):
- `NO_REPEAT_MEALS` varsayılanı false: araçlar tekrar yüzünden reddetmez.
- `variety_notes` / `variety_block` (`app/agent/tools.py`): ogun_degistir, ogun_ekle,
  plan_kaydet ve plani_getir sonucuna "Çeşitlilik gözlemleri (kural değil...)" ekler; uygulamaya
  giden mesajlardan API keser.
- İstemde "## Düşünerek seç" bölümü; Gemini isteklerinde `ThinkingConfig(thinking_level=HIGH)`
  (`GEMINI_THINKING_LEVEL`), 400 "thinking" hatasında o model için ayarsız tekrar ve hatırlama.
- Kontroller: pytest 370 geçti. **Doğrulanmadı:** düşünme seviyesinin gerçek modelde cevap
  süresine etkisi (turlar uzayabilir) ve çeşitliliğe gerçek etkisi.

## Son tamamlanan iş (Claude, 2026-10-25): tekrar yasağı, yepyeni yemek, Telegram'sız onay, PDF (1.8)

Kullanıcı: "Dünyada başka yemek yok mu? 2 gün arka arkaya aynı yemek; yeni tarif diyorum hâlâ
aynı şeyler"; "taslak onaylanmadan PDF paylaşılsın"; "onaylayınca Onaylı menü'de görünmeli,
Telegram'dan gitmiş, Telegram kullanmayacağım"; "onaylı menünün tarifleri Tarifler'de, PDF
ile paylaşılsın"; "onaylı menünün alışveriş listesi Alışveriş'e gitsin, paylaşılsın".

- **Tekrar yasağı (sunucu, ajan + elle düzenleme):** aynı ana yemek haftada bir kez, hiçbir
  yemek arka arkaya iki gün (hafta geçişi dahil). `MealAgentToolset._clash`, plan_kaydet
  denetimi; ayar `NO_REPEAT_MEALS` (varsayılan açık; küçük kütüphaneli eski testlerde kapalı).
  Otomatik planlayıcıya uygulanmaz.
- **`yenisiyle_degistir` aracı** (`app/agent/fresh.py`): kütüphane + bu hafta + son 4 haftanın
  yemeklerini ve ev kurallarını vererek tek JSON isteğiyle 3 farklı mutfaktan tarifli öneri
  alır; kütüphanede olmayan ve kurala uyan ilkini aday kaydedip `ogun_degistir` ile koyar.
  API `POST /menu/yenisi`; uygulamada yemeğe dokun → "Yerine yepyeni bir yemek bul" (sohbetsiz).
  Web araması yok (yapılandırılmış JSON ile birlikte kullanılamıyor); model bilgisinden.
- **Telegram'sız:** `TELEGRAM_MENU_MESSAGES=false` (varsayılan): onay (uygulama ve ajan),
  pazar taslağı ve keşif mesajları Telegram'a gitmez. Bağlantı kodu/güncelleme bildirimi sürer.
- **Uygulama 1.8 (versionCode 9):** Taslak/Onaylı bölümleri uygulamada `bu_hafta` +
  `gelecek_hafta` menülerinden seçilir (`bolumSec`; eski sunucuyla da çalışır — kullanıcının
  ekranında eski sunucu "onayli"yi tanımadığı için taslak görünüyordu). Onaydan sonra Onaylı
  menü açılır. Menü, tarifler (Tarifler > "Bu hafta", `GET /menu/tarifler`) ve alışveriş
  listesi PDF olarak paylaşılır (`ui/Pdf.kt`, PdfDocument + FileProvider `cache/pdf`, izin yok).
  Alışveriş onaylı menüyü (yoksa taslağı) izler ve kaynağını yazar.
- **Kontroller:** pytest 365 geçti; Android 58 test (5 canlı atlandı) geçti.
- **Doğrulanmadı:** PDF dosyasının cihazda yazılması (Robolectric PdfDocument'i taklit etmiyor;
  içerik satırları test edildi); gerçek Gemini'nin `yenisiyle_degistir` önerilerinin kalitesi.
- **Sıradaki adım:** kullanıcı `/guncelle` (ya da Ayarlar) + 1.8 APK.

## Son tamamlanan iş (Claude, 2026-10-24): "Bunu anlayamadım" düşmeleri, ** işaretleri (1.7)

Kullanıcı ekran görüntüsü: "pancarı da değiştirelim son olarak" -> kırmızı "Bunu anlayamadım".
Kod incelemesi: bu metin anlama hatası değil; Gemini boş aday döndürünce (araç sonucundan
sonra ara sıra, MALFORMED_FUNCTION_CALL vb.) ya da adım sınırına (12) gelince
`_finish` boş metni "anlayamadım" yapıyordu. Sunucu günlüğü görülmedi; hangisi olduğu
doğrulanmadı.

- `gemini_backend.run_turn`: boş aday / yalnızca düşünce parçası -> en fazla 2 kez "(Sistem
  notu) ..." ile dürtme; adım sınırında araçsız (`FunctionCallingConfig(mode="NONE")`) son
  istekle özet. `runner._finish`: metin yine boşsa ama plan değiştiyse "Taslağı güncelledim"
  (ok=True, uygulama Taslak'a geçer); değişmediyse dürüst "model boş döndü" mesajı.
- İstem: kısa takip mesajlarını ("pancarı da", "onu da çıkar") konuşma + plandan anla;
  uygulama kanalında düz metin (** yok). Uygulama 1.7: `sadeMarkdown` ** kalın gösterir.
- Kontroller: pytest 352 geçti; Android 53 test (5 canlı atlandı) geçti; assembleRelease tamam.

## Son tamamlanan iş (Claude, 2026-10-24): Menü > Taslak bölümü (uygulama 1.6)

Kullanıcı (1.5 kurulu, sunucu güncel): "Taslağı her değişiklik sonrası bu tabloda görmek
istiyorum; menü içine Taslak bölümü yap, şu an hiçbir yerde göremiyorum."

- Sunucu: `/menu`, `/menu/onayla` için `hafta=taslak|onayli` (`draft_session`,
  `approved_session` in `app/api.py`); test `test_app_sections_draft_and_approved`.
- Uygulama 1.6 (versionCode 7): Menü sekmesi "Taslak" / "Onaylı menü"; asistan taslağı
  değiştirince otomatik Taslak'a geçiş + "Son değişiklik" kutusu + vurgu; elle düzenlemede
  de aynı kutu. Alışveriş listesi "aktif" haftayı izler (bölümden bağımsız).
- Düzeltme: uygulama düzenleme uçlarına "taslak" gönderiyordu (sunucu bunu kabul etmez);
  artık planın kendi haftası gider.
- Kontroller: Android testleri geçti (EkranTest 14, MetinTest 7), pytest 349 geçti;
  Robolectric ekran görüntüsü gözle kontrol edildi.
- Sıradaki adım: kullanıcı sunucuyu `/guncelle` ile güncelleyip 1.6'yı kursun.

## Son tamamlanan iş (Claude, 2026-10-24): haftalık meze listesi, asistan ana ekran (1.5)

Kullanıcı 1.4'ü beğenmedi: asistan menünün altında küçük kalıyordu, değişiklikler ekrandaki
menüye yansımıyordu, "mezeleri öğünlere ekleme" (= EKLEME) ve "mezeler günlere bölünmesin"
istekleri yapılamıyordu. Not: önceki turda "ekleme" yanlışlıkla "ekle" diye okunmuştu.
İki tasarım taslağı (claude.ai artifact) reddedildi; kullanıcı "asistan ön planda" ve
"menü tek bakışta" seçti.

- **Sunucu:** haftalık meze listesi, `ogun_ekle`/`ogun_cikar`, tarihten hafta bulma,
  `hafta` parametresi, sohbet cevabında `menu` + `degisiklikler`, uygulama kanalı istemi.
  Ayrıntı: PROJE.md > Haftalık meze listesi.
- **Uygulama 1.5 (versionCode 6):** Asistan ana ekran (tam ekran sohbet; plan değişince
  "Değişenler" + kompakt hafta tablosu kartı, Menüyü aç / Onayla). Menü sekmesi tek bakışta
  tablo + haftalık mezeler; yemeğe dokun → tarif / asistan yenilikçi koysun / asistana yaz /
  listeden değiştir / güne ekle / çıkar. Yeni dosyalar `ui/MenuTablosu.kt`, `ui/Asistan.kt`
  (yeniden yazıldı), `ui/GoruntuTest.kt` (yalnızca `GORUNTU` ortam değişkeniyle çalışır).
- **Kontroller:** `pytest -q` 348 geçti; Android `testDebugUnitTest` 50 test (5 canlı test
  atlandı) geçti; `assembleRelease` başarılı; ekran görüntüleri Robolectric ile çizilip
  gözle kontrol edildi.
- **Doğrulanmadı:** gerçek Gemini'nin yeni araçları (ogun_ekle/ogun_cikar) doğru seçmesi.
- **Kullanıcıya not:** sunucudaki mevcut taslak eski biçimde (günlerde meze) kalır; asistana
  "gelecek haftanın menüsünü yeniden hazırla" demek ya da pazar planını beklemek gerekir.
  Eski "her güne tek meze" gibi bir kural varsa Kurallar'dan silinmeli.

## Son tamamlanan iş (Claude, 2026-10-24): haftalık yeni yemekler + asistan menünün içinde

Kullanıcı: "Asistanla da olsa tarif listesinden dışarı çıkmıyor, her hafta sıradışı şeyler
de eklesin; menü ayrı sekme olunca güzel olmadı, asistan menüye gömülü olsun." Ardından:
"Haftalık menü otomatik gelsin; x, y, z olmamış daha yenilikçi şeyler ekle deyince tariflere
de internetteki sıradışı tariflere de bakıp öneride bulunsun, kuralları baz alsın."

- **Sunucu:** adaylar menüye "yeni yemek" olarak girebilir (`plan_kaydet`, `ogun_degistir`;
  pasifler hâlâ giremez). `WEEKLY_NEW_DISHES=2` + ev kuralı ("her hafta 3 sıradışı yemek
  olsun" / "yeni yemek ekleme"). Pazar otomatik planı denenmemiş adayları yerleştirir
  (`app/planner/novelty.py`), yine eksikse ajan internetten bulup ekler. İstemde "bunlar
  olmamış, daha yenilikçi koy" akışı (kütüphane + zorunlu web araması + kurallar). Menü
  JSON'unda `yeni`, Telegram'da "✨ yeni". Ayrıntı: PROJE.md > Haftalık yeni yemekler.
- **Uygulama 1.4 (versionCode 5):** alt menü 4 sekme (Menü, Alışveriş, Tarifler, Kurallar);
  asistan Menü ekranının altında (`ui/Asistan.kt`: panel, seçim çubuğu, yazı alanı). Öğüne
  dokununca seçilir → "Daha yenilikçi bir şey koy" / "Listeden seç" / yaz; giden mesaj seçili
  yemekleri tarih+slotla taşır (`seciliMesaj`). Tarif kitabı simgesi tarifi açar.
- **Değişen dosyalar:** app/agent/{prompts,tools}.py, app/memory/rules.py, app/config.py,
  app/planner/{novelty,service}.py, app/scheduler/weekly.py, app/api.py, app/formatting.py,
  tests/test_new_dishes.py (yeni), tests/test_agent_tools.py, Android ui/* + Modeller.kt +
  testler + örnek JSON'lar, belgeler.
- **Kontroller:** `pytest -q` → 326 geçti. Android `testDebugUnitTest` geçti (EkranTest 12,
  MetinTest 4, ModelTest 8…), `assembleRelease` başarılı. Ekran görüntüsü Robolectric'te
  çizilip gözle kontrol edildi (menü + asistan paneli, seçim çubuğu).
- **Doğrulanmadı:** gerçek Gemini'nin "daha yenilikçi" isteğinde gerçekten web araması
  yapıp kurala uygun yemek koyması; pazar işinde ajan yedeğinin gerçek süresi.
- **Sıradaki adım:** kullanıcı sunucuyu güncellesin (telefondan `/guncelle` ya da uygulamada
  Ayarlar → Sunucuyu güncelle; bu özellik henüz kurulmadıysa bir kez bilgisayardan
  `./deploy/sunucu-guncelle.sh`), 1.4 APK'yı kursun, bir taslakta yemek seçip denesin.

## Son tamamlanan iş (Claude, 2026-10-24): sunucuyu telefondan güncelleme

Kullanıcı telefondaydı ve sunucuyu güncelleyemedi (SSH anahtarı Mac'te). Artık:
Telegram `/guncelle`, `/surum`; uygulama 1.3 Ayarlar → "Sunucuyu güncelle" (sürüm de görünür);
API `POST /api/v1/guncelle`, `/durum`'da `surum`, `aciklama`, `guncelleniyor`.
Ayrıntı PROJE.md > Canlı ortam. Testler: `tests/test_updater.py` betiği gerçek git
depolarıyla, sahte python/sudo ile çalıştırır (zaten güncel / güncelle+etiketle+yeniden başlat /
`git pull` hatası → bildir, yeniden başlatma yok). `pytest` 306 geçti, Android testleri geçti.

**Doğrulanmadı (ilk gerçek kullanımda görülecek):** sunucuda `sudo -n systemd-run` ve
servis içinden sudo'nun çalışması. Bu özelliğin sunucuya ilk kurulumu için bir kez
bilgisayardan `./deploy/sunucu-guncelle.sh` gerekiyor (kullanıcıya söylendi).

## Son tamamlanan iş (Claude, 2026-10-24): uzun asistan işleri arka planda

- **Sorun (kullanıcı ekran görüntüsü):** mobil veride uzun bir meze listesi fotoğrafıyla
  "bunları mezelere ekle" → uygulamada "Sunucuya ulaşılamadı". Sunucu günlüğü görülmedi;
  en olası sebep: tek bir uzun bekleyen HTTPS isteği (dakikalarca veri akmıyor) mobil
  operatör / Honor arka plan kısıtlaması yüzünden kopuyor, sunucu ise işi bitiriyor.
- **Düzeltme:** API'ye arka plan işleri: `POST /sohbet/baslat`, `POST /kesif/baslat` →
  `{"is": id}`, `GET /is/{id}` → `calisiyor|bitti|hata`. İş bellekte (1 saat), süre sınırı
  `AGENT_JOB_TIMEOUT_SECONDS=600`. Eski `POST /sohbet` (uygulama 1.1 için) duruyor.
  Uygulama 1.2: `IsBekleyici` işi başlatır, 2,5 sn'de bir sorar, ağ hatasında sessizce
  yeniden dener (12 dk'ya kadar), sunucu eskiyse (404) eski yola düşer; geçen süreyi gösterir.
- Ayrıca: `AGENT_MAX_TOKENS` 8000 → 16000 (toplu tarif ekleme uzun cevap), istek zaman aşımı
  60 → 90 sn.
- Kontroller: `pytest` 290 geçti; Android testleri geçti (`IsBekleyiciTest`: kopma, eski
  sunucu, kayıp iş, süre aşımı); `CanliSunucuTest` 5/5 (gerçek istemci ↔ gerçek HTTPS API,
  6 sn'lik iş sorularak alındı).
- **Doğrulanmadı:** sunucu günlüğüyle asıl kopma sebebi; gerçek Gemini'nin uzun listeyi
  600 sn içinde bitirmesi.

## Son tamamlanan iş (Claude, 2026-10-24): asistana görsel, her şey asistanla

Kullanıcı: "AI asistana görüntü ekleme getir (yemek listesini fotoğraflayıp 'bunları
database'e ekle' diyeceğim); her şeyi asistanla yapmak istiyorum."

- **Görsel:** `MealPlannerAgent.reply(..., images=[Gorsel(mime, data)])`; Gemini'ye satır içi
  parça, Claude'a base64 görsel bloğu. Geçmişe bayt değil "[N görsel eklenmişti]" notu.
  API `/sohbet` `gorseller` (en fazla 4, tür ve base64 denetimi); Telegram'da fotoğraf ve
  görsel dosyası `handlers.photo` ile asistana gider. İstemde görsel bölümü (liste → tarif_ara,
  yoksa tarif_ekle, "ekle" dendiyse tarif_onayla; tarif sayfası → okunduğu gibi kaydet).
- **Eksik araçlar:** `menuyu_onayla` (yalnızca kullanıcı o mesajda açıkça isterse; Telegram
  varsa alıcılara gönderir — eskiden ajanın bu yetkisi yoktu, kullanıcı istedi) ve `kiler`.
- **Uygulama 1.1:** Asistan'da 📷 düğmesi (galeriden seç / fotoğraf çek), önizleme ve
  silme, metinsiz gönderme. Fotoğraf 1600 px JPEG'e küçültülür. Yeni izin yok (PROJE.md).
- Kontroller: `pytest -q` → **285 geçti**; Android `testDebugUnitTest` geçti (görsel ölçek,
  gövde biçimi, ekran akışı); `CanliSunucuTest` 4/4 — gerçek istemciden 200 KB görsel gerçek
  HTTPS API'ye bozulmadan (SHA-256 aynı) ulaştı; release APK izinleri yalnızca INTERNET.
- **Doğrulanmadı:** gerçek Gemini'nin gerçek bir liste fotoğrafını okuyup tarifleri eklemesi;
  telefonda kamera akışı. Sunucuya kurulum: `./deploy/sunucu-guncelle.sh`.

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
