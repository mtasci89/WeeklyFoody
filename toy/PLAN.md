# Kelime Kaşifi — Konuşan İngilizce Öğrenme Oyuncağı

**Hedef kullanıcı:** 5–7 yaş, ana dili Türkçe, İngilizce öğreniyor.
**Ana dil:** İngilizce. **Türkçe rolü:** sadece "can simidi" — çocuk takıldığında açıklama, asla varsayılan konuşma dili değil.
**Yaklaşım:** Önce yazılım (Faz 0–1), doğrulandıktan sonra donanım (Faz 2–3).

---

## 0. Tasarımın dayandığı 5 karar

Bu projede teknoloji seçimlerinden daha önemli olan şey, aşağıdaki beş karardır. Kod bunların üzerine kurulur.

### K1 — LLM sıcak yolda (hot path) çalışmaz

Çocuk bir şey söyledikten sonra cevabı **1 saniyeden kısa** sürede duymalı. 5 yaşındaki bir çocuk 2 saniyelik sessizlikte oyundan kopar. Bu yüzden:

- **Oyun içi tepkiler** (doğru/yanlış, övgü, ipucu, tekrar) → deterministik durum makinesi + **önceden üretilmiş ses dosyaları**. Sentez süresi 0 ms, sadece dosya oynatma.
- **LLM sadece çevrimdışı** çalışır: gece batch işiyle yeni hikâyeler, yeni cümle varyasyonları, yeni ipuçları üretir; hepsi TTS'ten geçirilip diske yazılır.
- Tek istisna: "Serbest Hikâye" modu (Faz 1 sonu). Orada 1,5 sn gecikme kabul edilebilir çünkü çocuk zaten dinleme modundadır.

Bu, projenin en önemli mimari kararı. "Yerel LLM'e mikrofon bağlayalım" yaklaşımı çocuk oyuncağında çalışmaz.

### K2 — Serbest transkripsiyon değil, kısıtlı eşleştirme

Whisper, 5 yaşındaki bir Türk çocuğunun İngilizcesinde serbest modda çok kötü çalışır. Ama bizim buna ihtiyacımız yok: her an çocuğun ne söylemesi **beklendiğini** biliyoruz (hedef kelime + 3–5 çeldirici).

Yani problem "bu ses ne diyor?" değil, **"bu ses N adaydan hangisine daha yakın?"**. Çözüm katmanları:

1. `faster-whisper` + `initial_prompt` ile aday kelimelere bias, `beam_size=1`, dil sabit `en`.
2. Çıkan metni hedef kelimelerle **fonem düzeyinde** karşılaştır (`espeak-ng` ile G2P + ağırlıklı Levenshtein). "chair" yerine "çer" yazsa bile eşleşir.
3. Eşik cömert. Yanlış "yanlış" demek, yanlış "doğru" demekten çok daha zararlıdır.

### K3 — Bas-konuş (push-to-talk), otomatik dinleme yok

VAD (ses aktivitesi tespiti) çocuk odasında felakettir: televizyon, kardeş, kendi mırıldanması. Faz 0'da ekranda büyük bir buton, Faz 2'de kutunun üstünde fiziksel bir arcade butonu. Çocuk basılı tutar, konuşur, bırakır. Bu tek karar hata oranını yarıya indirir.

### K4 — Telaffuz notlanır ama asla cezalandırılmaz

Fonem mesafesinden 0–100 arası bir skor çıkarıyoruz. Bu skor **çocuğa gösterilmez**. Sadece:
- Tekrar sıklığını belirler (SRS aralığı).
- Ebeveyn panelinde "bu hafta zorlandığı sesler: /θ/, /r/" olarak görünür.

Çocuğa dönen geri bildirim üç kademelidir: `Harika!` / `Çok yaklaştın, bir daha: chaaair` / `Ben söyleyeyim, sen tekrar et.` Dördüncü kademe yok — asla "yanlış" denmez.

### K5 — Türkçe bir ödül değil, bir merdivendir

Çocuk Türkçeye kaçmayı öğrenirse İngilizce çalışmaz. Kurallar:
- Türkçe **sadece** çocuk açıkça isteyince gelir: "anlamadım" der veya kutudaki mavi butona basar.
- Türkçe açıklamadan sonra **her zaman** İngilizce cümle tekrar edilir ve çocuktan tekrar istenir. Yani Türkçe hiçbir zaman turun son sözü değildir.
- Türkçe kullanım sayacı ebeveyn panelinde görünür. Haftalar içinde düşmesi beklenir; düşmüyorsa seviye çok zor demektir, müfredat otomatik geri alınır.

---

## 1. Oyunlar (içerik = projenin gerçek zorluğu)

Teknoloji 2 haftada biter; çocuğun 3. hafta hâlâ oynamak istemesi asıl iştir. Bu yüzden 6 oyun, artan zorlukta:

| # | Oyun | Ne öğretir | Konuşma gerekir mi | Faz |
|---|------|-----------|--------------------|-----|
| 1 | **Simon Says** — "Touch your nose!", "Jump twice!" | Dinlediğini anlama, komut fiilleri, vücut/hareket kelimeleri | Hayır (sadece hareket) | 0 |
| 2 | **Name It** — kart/resim gösterilir, çocuk İngilizce söyler | Kelime üretimi, telaffuz | Evet, tek kelime | 0 |
| 3 | **I Spy** — "I spy something red in this room!" | Sıfatlar, renkler, odadaki nesneler, keşif | Evet, tek kelime | 0 |
| 4 | **Echo & Rhyme** — kısa tekerleme, çocuk tekrar eder | Prozodi, akıcılık, ritim | Evet, kalıp cümle | 1 |
| 5 | **Story Buddy** — 4 cümlelik hikâye + 1 soru | Bağlam içinde kelime, dinleme | Evet, kısa cevap | 1 |
| 6 | **Free Chat** — serbest sohbet, LLM canlı | Üretken konuşma | Evet, serbest | 1 sonu |

**Oturum tasarımı:** 6–8 dakika, 3 mini oyun, sonunda bir "rozet". Uzun oturum yok. Günde en fazla 2 oturum, sistem üçüncüyü nazikçe reddeder ("Yarın devam edelim, ben biraz uyuyacağım").

**Müfredat:** ~300 kelimelik çekirdek liste (Oxford Phonics / Dolch sight words temelli), 12 tematik ünite (renkler, hayvanlar, yiyecek, aile, vücut, oyuncaklar, hava, sayılar, hareketler, ev, kıyafet, duygular). Her ünite 20–25 kelime. Kelime seçimi **SRS** ile: Leitner kutuları (1 gün / 3 gün / 7 gün / 21 gün), telaffuz skoru düşükse kutu ilerlemez.

---

## 2. Mimari

```
┌─────────────────────────── GX10 (beyin) ────────────────────────────┐
│                                                                      │
│  content-builder (gece, batch)          runtime (canlı, hızlı)      │
│  ┌──────────────────────┐               ┌────────────────────────┐  │
│  │ LLM (Qwen3 / Gemma3) │               │ FastAPI + WebSocket    │  │
│  │  → hikâye, cümle,    │               │  ├─ ASR: faster-whisper│  │
│  │    ipucu, çeldirici  │──── yazar ───▶│  ├─ Matcher: G2P+fonem │  │
│  │ TTS (Piper/Kokoro)   │   audio_cache/ │  ├─ Oyun durum makinesi│  │
│  │  → .wav önbelleği    │   content.db  │  ├─ SRS motoru         │  │
│  └──────────────────────┘               │  └─ Oturum kaydı(SQLite)│ │
│                                          └───────────┬────────────┘  │
└──────────────────────────────────────────────────────┼──────────────┘
                                                       │ LAN / WebSocket
                         ┌─────────────────────────────┼──────────────┐
                         │                             │              │
                  Faz 0–1: Tablet PWA          Faz 2: ESP32-S3 kutu   │
                  (mikrofon + ekran)           (mic + hoparlör + LED  │
                                                + NFC kart + buton)   │
                         │                                            │
                  Ebeveyn paneli (React) ◀── aynı API ────────────────┘
                  + günlük Telegram raporu
```

**Neden bu ayrım:** `content-builder` yavaş ve akıllı, `runtime` aptal ve hızlı. Runtime'da model çıkarımı sadece ASR'dir (~200–400 ms, kısa klipler). Geri kalan her şey sözlük araması ve dosya oynatma.

### Model seçimleri (GX10 üzerinde)

| Görev | Model | Not |
|-------|-------|-----|
| ASR | `faster-whisper large-v3-turbo`, int8_float16 | Kısa klip + kısıtlı aday listesi ile yeterli. Yetmezse `wav2vec2-lv60-espeak-cv-ft` ile fonem çıktısı ekleyeceğiz. |
| Telaffuz/G2P | `espeak-ng` (hedef fonemler) + ağırlıklı Levenshtein | Nöral hizalayıcıya Faz 1'de bakarız; başlangıçta gerek yok. |
| TTS (İngilizce) | Piper (`en_US-amy` / çocuk dostu ses) veya Kokoro | Batch'te üretilir, önbelleğe yazılır. Karakter sesi tutarlı olmalı. |
| TTS (Türkçe) | Piper `tr_TR-dfki` | Sadece can simidi cümleleri, sayıca az. |
| İçerik LLM | Qwen3-30B veya Gemma3-27B, yerel | Gece çalışır, gecikme önemsiz. Bulut kullanmıyoruz (ses/çocuk verisi dışarı çıkmaz). |

### Gecikme bütçesi (hedef)

```
buton bırakıldı ──▶ ses yükleme     40 ms
                    ASR            300 ms
                    fonem eşleşme    5 ms
                    yanıt seçimi     1 ms
                    önbellek .wav    5 ms
                    oynatma başladı ─────────  ~350 ms  ✅
```

---

## 3. Repo yapısı

Bu repo (`WeeklyFoody`) altında bağımsız bir `toy/` ağacı. Mevcut projeden **yeniden kullanılacaklar**: `app/llm/base.py` sağlayıcı soyutlaması, `app/db/` SQLAlchemy kalıbı, `app/config.py` pydantic-settings kalıbı, `src/` React+Tailwind+shadcn kurulumu (ebeveyn paneli için), Telegram bot kalıbı (günlük rapor için).

```
toy/
├── PLAN.md                  # bu dosya
├── server/
│   ├── config.py            # pydantic-settings
│   ├── main.py              # FastAPI + /ws/session
│   ├── asr/
│   │   ├── engine.py        # faster-whisper sarmalayıcı
│   │   └── matcher.py       # G2P + fonem mesafesi + eşik
│   ├── tts/
│   │   ├── synth.py         # Piper sarmalayıcı
│   │   └── cache.py         # metin → sha1 → .wav önbelleği
│   ├── games/
│   │   ├── base.py          # Game protokolü: next_turn / on_answer
│   │   ├── simon_says.py
│   │   ├── name_it.py
│   │   ├── i_spy.py
│   │   ├── echo_rhyme.py
│   │   └── story_buddy.py
│   ├── curriculum/
│   │   ├── words/*.yaml     # 12 ünite, kelime + TR karşılık + fonem + resim
│   │   ├── srs.py           # Leitner
│   │   └── selector.py      # bugün hangi kelimeler
│   ├── content/
│   │   └── builder.py       # gece batch: LLM → metin → TTS → önbellek
│   ├── db/models.py         # Child, Word, Attempt, Session, Badge
│   └── report/telegram.py   # ebeveyne günlük özet
├── client/                  # Faz 0: tablet PWA (React, mikrofon + büyük butonlar)
├── dashboard/               # ebeveyn paneli (mevcut src/ kurulumunu paylaşır)
└── firmware/                # Faz 2: ESP32-S3 (PlatformIO)
```

### Veri modeli (çekirdek)

```
Word(id, en, tr, unit, phonemes, image, difficulty)
Attempt(id, word_id, ts, game, asr_text, phoneme_score, accepted, hint_level, tr_lifeline)
WordState(word_id, box, due_at, streak, avg_score)   # SRS
Session(id, started, ended, games[], words_seen, tr_lifeline_count, engagement_score)
Badge(id, name, earned_at, criteria)
```

`Attempt` her denemeyi saklar — ilerleme raporunun, SRS'in ve "hangi ses zor" analizinin tek kaynağı budur.

---

## 4. Fazlar

### Faz 0 — Yazılım prototipi (hedef: 1–2 hafta, sıfır donanım harcaması)

Amaç **kodu bitirmek değil, çocuğun ilgisini ölçmek.**

1. FastAPI + WebSocket iskeleti, tabletten açılan PWA istemci (bas-konuş butonu).
2. `faster-whisper` + fonem eşleştirici, 20 kelimelik tek ünite ("Animals").
3. Piper TTS + önbellek; tüm istemler önceden üretilmiş.
4. Üç oyun: Simon Says, Name It, I Spy.
5. Türkçe can simidi butonu.
6. Her oturum JSONL olarak loglanır.

**Faz 0 çıkış kriteri (ölçülebilir):**
- 5 gün üst üste kullanım, çocuk **kendisi isteyerek** en az 3 kez oturum başlatıyor.
- Ortalama oturum ≥ 4 dakika.
- ASR kabul oranı ≥ %70 (tanınmayan cevap oranı ≤ %30).
- Türkçe can simidi kullanımı %40'ın altında.

Bu kriterler tutmazsa **donanıma geçilmez** — oyun tasarımı değiştirilir. Bu, projenin en pahalı hatasını (çalışmayan bir fikre 200 € donanım) önleyen kapıdır.

### Faz 1 — İçerik motoru, ilerleme, ebeveyn (2–3 hafta)

- 12 ünite / ~300 kelime müfredatı, SRS.
- Gece batch içerik üretimi (LLM → hikâye/cümle → TTS önbelleği).
- Echo & Rhyme, Story Buddy oyunları.
- Ebeveyn paneli: bilinen kelimeler, zorlanılan sesler, haftalık grafik, oturum kayıtları.
- Günlük Telegram özeti (mevcut bot altyapısıyla).
- Rozet/ödül sistemi, oturum limiti.

### Faz 2 — Fiziksel kutu (donanım burada devreye girer)

Faz 0 kriterleri tuttuğunda. **Not: "Arduino" burada doğru kart değil.** Klasik Arduino Uno'da ne WiFi ne de ses işleme kapasitesi var. Doğru seçim **ESP32-S3** (WiFi + I2S ses + yeterli RAM) — Arduino IDE/PlatformIO ile aynı şekilde programlanır, yani Gemini'nin kastettiği "fiziksel dünya" rolünü ESP32-S3 üstlenir.

Alışveriş listesi (yaklaşık, ~90–120 €):

| Parça | Örnek | ~Fiyat | Görev |
|-------|-------|--------|-------|
| ESP32-S3 DevKitC-1 (N16R8) | Espressif | 12 € | Beyin–kas köprüsü, WiFi ses akışı |
| I2S mikrofon | INMP441 | 4 € | Çocuğun sesi |
| I2S amfi + hoparlör | MAX98357A + 3 W 4 Ω | 9 € | Karakterin sesi |
| LED halka | WS2812B 12–16 px | 6 € | "Gözler": dinliyorum / düşünüyorum / aferin |
| Arcade buton ×2 | 30 mm | 5 € | Yeşil = konuş, Mavi = Türkçe yardım |
| NFC okuyucu | PN532 | 9 € | **Resimli kartlar** — fiziksel kelime kartları |
| NFC etiket | NTAG213 ×50 | 12 € | Her kart bir kelime |
| LiPo 2000 mAh + TP4056 | — | 10 € | Kablosuz kullanım |
| Kutu | 3D baskı / ahşap | 15–40 € | Karakter gövdesi |

**NFC kartlar bu projedeki en değerli fiziksel fikir:** çocuk bir kartı kutuya dokundurur, kutu "What is this?" der. Ekran yok, elle tutulur nesne var, kelime dağarcığı fiziksel bir eşyaya bağlanır — 5–7 yaş için ekrandan çok daha etkili.

**Ara yol (isteğe bağlı):** İlk fiziksel prototipi Raspberry Pi Zero 2 W ile 1 haftada yapmak mümkün (USB ses, Python doğrudan çalışır, lehim/firmware derdi yok). Nihai oyuncak yine ESP32-S3 olur (açılış süresi ve pil ömrü). Hızlı sonuç istersen bu ara adımı öneririm.

### Faz 3 — Karakter ve dayanıklılık

- Kutu tasarımı/3D baskı, çocuğun isim vermesi.
- Çevrimdışı mod: GX10 kapalıysa ESP32 önbellekteki oyunları tek başına oynatır.
- Ses kişiliği: tutarlı karakter, duygu durumları (LED + prozodi).

---

## 5. Gizlilik ve güvenlik

- **Tüm ses işleme yerel.** Buluta hiçbir ses gitmez; içerik LLM'i de yerel çalışır.
- Ses kayıtları işlendikten sonra **varsayılan olarak silinir**. Ebeveyn "kayıtları 7 gün sakla" diyebilir (telaffuz gelişimini dinlemek için).
- Veritabanında kişisel tanımlayıcı yok — tek bir `child_id`.
- Kutu WiFi'de sadece GX10'a bağlanır; internet erişimi yok.
- Serbest sohbet modunda LLM çıktısı, yaş uygunluğu için beyaz liste + basit içerik filtresinden geçer; hikâyeler zaten gece batch'te üretilip **ebeveyn panelinde onaylanır**, canlı üretim onaylı havuzdan seçim yapar.

---

## 6. Başarı ölçütleri

Teknik metrikler değil, bunlar önemli:

1. **Gönüllü kullanım:** Çocuk haftada kaç kez kendisi istedi? (Hedef: ≥ 4)
2. **Üretim:** Haftada kaç yeni kelimeyi ipuçsuz, ilk denemede söyledi? (Hedef: ≥ 5)
3. **Kalıcılık:** 7 gün sonraki tekrarda doğru bilme oranı. (Hedef: ≥ %70)
4. **Bağımsızlık:** Türkçe can simidi kullanımının haftalar içindeki düşüşü.
5. **Transfer (asıl ödül):** Oyun dışında, günlük hayatta kendiliğinden İngilizce kelime kullanması. Ebeveyn panelinde tek tıkla işaretlenir.

**Durdurma kriteri:** 2. hafta sonunda çocuk oyuncağı kendiliğinden istemiyorsa teknolojiyi değil **oyunu** değiştiririz. Bu plan, kodu değil ilgiyi optimize eder.

---

## 7. Sıradaki adım

Faz 0'ın ilk dilimi (`server/` iskeleti + ASR + fonem eşleştirici + Name It oyunu + tablet istemcisi) tek bir çalışan uçtan uca akış olarak yazılabilir. Hedef: GX10'da `uvicorn` çalıştır, tabletten aç, çocuk butona basıp "cat" desin, kutu "Perfect! Cat!" desin.
