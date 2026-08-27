# English Mate — mevcut durum incelemesi ve plan karşılaştırması

**İncelenen:** `mtasci89/english-mate` @ `33c65d9` (tek commit, 14 dosya, ~1.260 satır kaynak)
**Durum:** `npm ci && npm run build` ✅ temiz, `tsc --noEmit` ✅ temiz.
**Sonuç: kod bozuk değil. Ürün tasarımı `PLAN.md`'nin beş temel kararının dördünü ihlal ediyor.**

---

## 1. Ne yapılmış (olgular)

| Katman | Gerçekleşen |
|--------|-------------|
| İstemci | Tek ekran React SPA. `src/App.tsx` 536 satır, tek dosya — bileşen ayrımı, router, test yok. |
| ASR | Tarayıcı `webkitSpeechRecognition`, `lang="en-US"`, serbest transkripsiyon, kısıt yok. |
| TTS | Tarayıcı `speechSynthesis` — işletim sisteminin robot sesi. |
| Zeka | Her tur için Netlify Function → Gemini 2.0 Flash. |
| Kalıcılık | Yok. `localStorage`'da 4 ayar. Konuşma geçmişi RAM'de, son 7 mesaj, yenilemede kayıp. |
| Oyun | Yok. Tek mod: serbest sohbet. |
| Müfredat | Yok. 4 konu × 3 sabit soru = 12 cümle, modulo ile döngü. |
| İlerleme | Yok. Hiçbir deneme kaydedilmiyor. |
| Ebeveyn paneli | 4 canlı ayar düğmesi (seviye/konu/düzeltme/Türkçe köprüsü). Rapor yok. |

Yani: **çalışan bir çocuk sohbet botu**, öğrenme aracı değil.

---

## 2. Beş temel karara göre karşılaştırma

### K1 — LLM sıcak yolda çalışmaz ❌ **Tamamen ihlal**

Her tur şu zinciri geçiyor:

```
çocuk konuşur
  → tarayıcı ASR sessizlik bekler + Google'a gider     700–1500 ms
  → fetch /api/chat (Netlify soğuk başlangıç olabilir)  200–2000 ms
  → Gemini Flash üretimi                                600–1200 ms
  → speechSynthesis başlar
                                          TOPLAM  ≈ 1,5 – 4,5 sn
```

Plandaki hedef ~350 ms idi. Gerçekleşen bunun **5–12 katı**. 5 yaşındaki bir çocuk 2 saniyelik sessizlikte oyundan kopar — bu tek başına "istediğim gibi olmadı" hissinin en olası teknik sebebi. Üstelik Türkiye'den Netlify + Google API'ye çift kıtalararası gidiş var.

Plandaki çözüm (önceden üretilmiş `.wav` önbelleği + deterministik durum makinesi) hiç uygulanmamış. `buildFallbackResponse()` doğru içgüdü ama sadece **hata durumunda** devreye giriyor; asıl yol olması gerekiyordu.

### K2 — Serbest transkripsiyon değil, kısıtlı eşleştirme ❌ **Yok**

`recognition.lang = "en-US"`, gramer/aday listesi/bias yok, fonem karşılaştırması yok. Türk çocuğunun İngilizcesinde serbest tarayıcı ASR'si düşük doğrulukla çalışır.

Daha derin sorun: **doğru/yanlış kavramı hiç yok.** Serbest sohbette çocuğun ne söylemesi beklendiği tanımlı olmadığı için sistem hiçbir zaman "bunu bildi" diyemez. Bu yüzden aralıklı tekrar da, ilerleme raporu da, ebeveyn geri bildirimi de **mimari olarak imkânsız**. Ölçüm eksikliği bir özellik boşluğu değil, tasarımın doğrudan sonucu.

### K3 — Bas-konuş ⚠️ **Yarım**

"Start listening" butonu var ama `continuous = false` → tanıma **sessizlikte kendi kendine kesiyor**. Basılı tutma yok. Cümlenin ortasında duraksayan çocuk kesiliyor.

Dahası `App.tsx:335-343`: `no-speech` hatasında oyuncak *"I could not hear that clearly. Please try again."* diyor. Yani tereddüt eden çocuk azarlanıyor. K4'ün ("asla cezalandırma") ruhuna aykırı ve davranışsal maliyeti gerçek.

### K4 — Telaffuz notlanır, cezalandırılmaz ❌ **Yok**

Fonem skoru yok, saklanan skor yok, "zorlandığı sesler" analizi yok. Düzeltme sadece Gemini'nin düzyazı içinde yeniden ifade etmesiyle (recast) yapılıyor — pedagojik olarak makul, ama hiçbir şey bunun tutup tutmadığını izlemiyor.

### K5 — Türkçe merdiven olmalı, kaçış kapısı değil ❌ **Ters uygulanmış**

Üç ayrı sorun:

1. **Kalıcı "Listen in Turkish" butonu** (`App.tsx:404-410`). Ekranda her an duran, tek tıkla Türkçeye geçiren düğme — planın açıkça engellemek istediği kaçış kapısının ta kendisi. Çocuk zorlandığında İngilizceyi denemek yerine butona basmayı öğrenir.
2. **Türkçe turun son sözü olabiliyor.** `buildFallbackResponse` Türkçe dalında (`App.tsx:165-173`) Türkçe cümleyle bitiyor, ardından İngilizce tekrar istenmiyor. Gemini prompt'u ("offer one easy English phrase and continue") daha iyi ama zorlayıcı değil.
3. **Sayaç yok.** Türkçe kullanımının haftalar içinde düşüp düşmediği ölçülmüyor — ki plandaki en önemli bağımsızlık göstergesiydi.

---

## 3. Kapsam karşılaştırması

| Plandaki | English Mate'te |
|----------|-----------------|
| 6 oyun (Simon Says → Free Chat, artan zorluk) | Sadece **Free Chat** — planın *en son ve en zor* modu |
| ~300 kelime, 12 ünite, Leitner SRS | 12 sabit sohbet sorusu |
| SQLite: Word / Attempt / WordState / Session / Badge | Veritabanı yok |
| Ebeveyn paneli: bilinen kelimeler, zor sesler, haftalık grafik | 4 ayar düğmesi |
| Günlük Telegram özeti | Yok |
| Rozet, oturum limiti (günde 2) | Yok |
| Faz 0 çıkış kriteri: 5 gün, 3 gönüllü oturum, %70 ASR kabul, <%40 Türkçe | **Ölçülemez** — hiçbir şey loglanmıyor |
| Tüm işleme yerel (GX10), ses buluta çıkmaz | Ses Google'a, metin Gemini'ye gidiyor. **GX10 hiç kullanılmıyor.** |
| ESP32-S3 + NFC resimli kartlar | README'de Raspberry Pi 5 + "opsiyonel ESP32"; NFC yok |

**En kritik satır sonuncudan bir öncekidir.** Faz 0'ın tüm amacı "çocuk bunu gerçekten istiyor mu?" sorusunu ölçmekti. Hiçbir deneme kaydedilmediği için bu soru cevaplanamaz. Muhtemelen "istediğim gibi olmadı" cümlesinin altında da tam olarak bu var: geri bildirim döngüsü yok, elde sadece bir his var.

---

## 4. Kök neden teşhisi

Tek cümleyle: **planın en zor modu (serbest konuşma), ilk gün tek mod olarak, en yüksek gecikmeyle ve sıfır ölçümle inşa edilmiş.**

5–7 yaş, İngilizceye yeni başlayan bir çocuğa "What did you do today?" diye sorulduğunda olan şey donup kalmaktır — cevap verecek kelime dağarcığı henüz yok. Plandaki Simon Says'in ilk sırada olmasının sebebi buydu: **konuşma gerektirmez**, sadece dinleyip hareket eder, ilk günden başarı hissi verir. Oradan Name It'e (tek kelime), sonra cümleye, en son serbest sohbete çıkılır.

English Mate bu merdiveni atlayıp doğrudan en üst basamaktan başlatıyor.

---

## 5. Korunması gerekenler

Baştan yazılacak bir şey yok; bu parçalar iyi ve taşınmalı:

- **Netlify Function deseni** — API anahtarı istemciye sızmıyor. Doğru yapılmış.
- **Sistem prompt'u** (`chat.mjs:25-38`) — gerçekten iyi yazılmış: sınıf jargonunu ("repeat after me", "grammar", "homework") açıkça yasaklıyor, ders vermek yerine recast istiyor, güvenlik yönlendirmesi var. **Faz 1'deki Free Chat modunun prompt'u olarak aynen kullanılabilir.**
- **Ayar şeması** (`level` / `topic` / `correctionStyle` / `turkishBridge`) — mantıklı; DB'deki çocuk profiline doğrudan dönüşür.
- **Deterministik yedek yanıt** — doğru fikir, yanlış yerde. Asıl yola terfi etmeli.
- **Güvenlik başlıkları** (`netlify.toml`: `Permissions-Policy = microphone=(self)`, `X-Frame-Options`, `nosniff`) — düşünülmüş.
- **Mobil öncelikli tek ekran** — tablet için doğru karar.

---

## 6. Somut hatalar (tasarımdan bağımsız)

1. **`chat.mjs:132`** — `lang` tespiti `/[çğıöşü]/i` ile yapılıyor. İçinde tek bir Türkçe kelime geçen tamamen İngilizce bir cevap `"tr"` etiketleniyor ve **tüm cümle Türkçe TTS sesiyle** okunuyor. Kulakta çok kötü.
2. **`chat.mjs:102`** — `maxOutputTokens: 90`, kesilme kontrolü yok. `finishReason: "MAX_TOKENS"` geldiğinde cümle ortasından kesilir ve öyle seslendirilir.
3. **`App.tsx:285`** — yedek yol `childTurns`'ü eski closure'dan okuyor; `messages.slice(-7)` birden fazla yerde geçmişi sessizce kırpıyor ve asistanın kendi son mesajını düşürebiliyor.
4. **`App.tsx:335-343`** — `no-speech` durumunda çocuğa "seni duyamadım" denmesi. Sessizlik bir hata değil, düşünme payıdır.
5. **Temizlik yok** — `recognition` ve `speechSynthesis` için `useEffect` cleanup'ı yok; sayfa değişince/kapanınca konuşma sürebiliyor.
6. **Gizlilik** — Chrome'un Web Speech API'si çocuğun **ses kaydını Google sunucularına yüklüyor**. Planda "tüm ses işleme yerel, buluta hiçbir ses gitmez" yazıyordu. Bu, farkında olarak verilmesi gereken bir karar.

---

## 7. Öneri: baştan yazma, "Faz 0.5" ile birleştir

Planımın dürüst özeti: English Mate'ten daha ağır. Yerel Whisper + Piper + fonem skorlama + gece içerik batch'i ciddi iş. English Mate ise **tek seferde canlı, çalışan bir URL'e** ulaşmış — bu gerçek bir değer ve atılmamalı.

Orta yol, mevcut kod tabanının üzerine üç şey ekler ve altyapıyı hiç değiştirmez:

**0.5-a — Merdiveni geri koy (en yüksek etki).** Serbest sohbeti *ikincil* moda al. Öne iki oyun koy:
- **Simon Says**: konuşma gerektirmez, komut listesi sabit, cevap "çocuk hareketi yaptı mı" değil "devam" butonudur. Sıfır ASR riski, ilk günden çalışır.
- **Name It**: resim + beklenen kelime. Artık **doğru/yanlış vardır** — bu tek değişiklik ölçümü, SRS'i ve raporu mümkün kılar.

**0.5-b — Gecikmeyi kır.** Bu iki oyunun tüm istemleri sabit metin. Bunları bir kez Gemini TTS veya Piper ile `.wav`'a çevirip `public/audio/` altına koy, `speechSynthesis` yerine `<audio>` ile çal. LLM ve robot ses sıcak yoldan çıkar; tepki ~300 ms'e iner. Free Chat modunda Gemini kalmaya devam eder.

**0.5-c — Ölç.** `Attempt` kaydı (kelime, oyun, ASR metni, kabul edildi mi, Türkçe can simidi kullanıldı mı, zaman damgası). Netlify Function + bir tablo (Netlify Blobs veya küçük bir SQLite/Turso) yeter. **Bu olmadan Faz 0 kapısı geçilemez ve donanıma geçme kararı yine hisle verilir.**

Ayrıca **"Listen in Turkish" butonunu kaldır**, yerine "I don't understand" butonu koy: Türkçe açıklamayı verir, ardından İngilizce cümleyi tekrarlar ve çocuktan tekrar ister, sayacı artırır. K5'in gerektirdiği davranış budur.

Bu üç adım tahminen birkaç günlük iş ve planın 4'ünü ihlal eden kararlarından 3'ünü düzeltir. Yerel model geçişi (GX10, gizlilik, gecikme) bundan sonra, ölçüm verisi elde olduğunda Faz 1'de anlamlı hale gelir.
