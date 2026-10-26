package com.foody.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.net.SocketTimeoutException
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.Base64
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLException
import javax.net.ssl.X509TrustManager

/**
 * Sunucunun kendinden imzalı sertifikasına güvenir, ama YALNIZCA açık anahtarı bağlantı
 * kodundaki pinle eşleşiyorsa. Araya giren biri başka bir sertifikayla gelirse bağlantı kurulmaz.
 */
class SabitAnahtarGuveni(private val pin: String) : X509TrustManager {
    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        val sertifika = chain?.firstOrNull() ?: throw CertificateException("Sunucu sertifika göndermedi")
        if (anahtarIzi(sertifika) != pin) throw CertificateException("Sunucu sertifikası beklenen anahtarla eşleşmiyor")
        sertifika.checkValidity()
    }

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) =
        throw CertificateException("İstemci sertifikası kabul edilmez")

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()

    companion object {
        /** SubjectPublicKeyInfo (DER) SHA-256, base64. Sunucuda: app/api_tls.py `spki_pin`. */
        fun anahtarIzi(sertifika: X509Certificate): String =
            Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-256").digest(sertifika.publicKey.encoded))
    }
}

/** Foody sunucusuyla konuşan istemci. Her çağrı arka planda çalışır; hata [Hata] olarak gelir. */
class Sunucu(private val ayarlar: () -> Ayarlar.Degerler) {
    class Hata(mesaj: String, val kod: Int? = null) : Exception(mesaj)

    private val jsonTip = "application/json; charset=utf-8".toMediaType()
    private var istemci: Pair<String, OkHttpClient>? = null

    private fun http(pin: String): OkHttpClient {
        istemci?.let { (eskiPin, c) -> if (eskiPin == pin) return c }
        val guven = SabitAnahtarGuveni(pin)
        val tls = SSLContext.getInstance("TLS").apply { init(null, arrayOf(guven), null) }
        val c = OkHttpClient.Builder()
            .sslSocketFactory(tls.socketFactory, guven)
            .connectTimeout(15, TimeUnit.SECONDS)
            // Asistan bir menüyü birkaç adımda kurar; bir tur birkaç dakika sürebilir.
            .readTimeout(300, TimeUnit.SECONDS)
            .callTimeout(320, TimeUnit.SECONDS)
            .build()
        istemci = pin to c
        return c
    }

    private suspend fun <T> cagir(
        yontem: String,
        yol: String,
        sorgu: Map<String, String> = emptyMap(),
        govde: String? = null,
        cevirici: KSerializer<T>,
    ): T = withContext(Dispatchers.IO) {
        val a = ayarlar()
        if (!a.hazir) throw Hata("Önce Ayarlar'dan bağlantı kodunu gir.")
        val url = "${a.adres}/api/v1/$yol".toHttpUrl().newBuilder().apply {
            sorgu.forEach { (k, v) -> addQueryParameter(k, v) }
        }.build()
        val istek = Request.Builder()
            .url(url)
            .header("Authorization", "Bearer ${a.anahtar}")
            .header("Accept", "application/json")
            .method(yontem, govde?.toRequestBody(jsonTip))
            .build()
        try {
            http(a.pin).newCall(istek).execute().use { r ->
                val metin = r.body?.string().orEmpty()
                if (!r.isSuccessful) throw Hata(hataMetni(r.code, metin), r.code)
                esnekJson.decodeFromString(cevirici, metin)
            }
        } catch (e: Hata) {
            throw e
        } catch (e: SSLException) {
            throw Hata("Sunucunun sertifikası beklenenden farklı. Telegram'da /uygulama ile yeni bağlantı kodu al.")
        } catch (e: SocketTimeoutException) {
            throw Hata("Sunucu zamanında cevap vermedi. Biraz sonra tekrar dene.")
        } catch (e: IOException) {
            throw Hata("Sunucuya ulaşılamadı. İnternet bağlantını ve sunucunun açık olduğunu kontrol et.")
        } catch (e: kotlinx.serialization.SerializationException) {
            throw Hata("Sunucunun cevabı okunamadı. Uygulamayı güncellemek gerekebilir.")
        }
    }

    suspend fun gunYemekleri(tarih: String) = cagir("GET", "caltrack/yemekler", mapOf("tarih" to tarih), cevirici = GunYemekleri.serializer())

    suspend fun durum() = cagir("GET", "durum", cevirici = DurumCevap.serializer())

    /** Sunucu kendini GitHub'daki son koda günceller ve yeniden başlar (deploy/kendini-guncelle.sh). */
    suspend fun sunucuyuGuncelle() = cagir("POST", "guncelle", govde = "{}", cevirici = MesajCevap.serializer())

    suspend fun menu(hafta: String = "aktif") = cagir("GET", "menu", mapOf("hafta" to hafta), cevirici = MenuCevap.serializer())

    suspend fun menuyuOnayla(hafta: String, planId: String? = null, versiyon: Int? = null) = cagir(
        "POST", "menu/onayla", govde = buildJsonObject { put("hafta", hafta); if (planId != null) put("plan_id", planId); if (versiyon != null) put("versiyon", versiyon) }.toString(), cevirici = MenuCevap.serializer(),
    )

    suspend fun ogunDegistir(tarih: String, slot: String, tarif: String, hafta: String = "aktif") = cagir(
        "POST", "menu/degistir",
        govde = buildJsonObject { put("tarih", tarih); put("slot", slot); put("tarif", tarif); put("hafta", hafta) }.toString(),
        cevirici = MenuCevap.serializer(),
    )

    /** Kütüphanede olmayan yepyeni bir yemek üretip öğüne koyar (sohbet gerekmez). */
    suspend fun yenisiniBul(tarih: String, slot: String, hafta: String, istek: String = "") = cagir(
        "POST", "menu/yenisi",
        govde = buildJsonObject { put("tarih", tarih); put("slot", slot); put("hafta", hafta); put("istek", istek) }.toString(),
        cevirici = MenuCevap.serializer(),
    )

    suspend fun menuTarifleri(hafta: String, kisi: Int = 0) = cagir(
        "GET", "menu/tarifler", mapOf("hafta" to hafta, "kisi" to kisi.toString()), cevirici = MenuTarifleri.serializer(),
    )

    /** Plana yemek ekler; `tarih` ISO ya da haftalık meze listesi için "HAFTA". */
    suspend fun ogunEkle(tarih: String, tarif: String, hafta: String = "aktif") = cagir(
        "POST", "menu/ekle",
        govde = buildJsonObject { put("tarih", tarih); put("tarif", tarif); put("hafta", hafta) }.toString(),
        cevirici = MenuCevap.serializer(),
    )

    suspend fun ogunCikar(tarih: String, slot: String, hafta: String = "aktif") = cagir(
        "POST", "menu/cikar",
        govde = buildJsonObject { put("tarih", tarih); put("slot", slot); put("hafta", hafta) }.toString(),
        cevirici = MenuCevap.serializer(),
    )

    suspend fun tarifler(aday: Boolean) = cagir(
        "GET", "tarifler", mapOf("durum" to if (aday) "aday" else "onayli"), cevirici = TarifListe.serializer(),
    )

    suspend fun tarif(id: String, kisi: Int) = cagir("GET", "tarifler/$id", mapOf("kisi" to kisi.toString()), cevirici = TarifDetay.serializer())

    suspend fun tarifiOnayla(id: String) = cagir("POST", "tarifler/$id/onayla", govde = "{}", cevirici = TarifIslemCevap.serializer())

    suspend fun tarifiCikar(id: String) = cagir("POST", "tarifler/$id/cikar", govde = "{}", cevirici = TarifIslemCevap.serializer())

    suspend fun alisveris(hafta: String = "aktif") = cagir("GET", "alisveris", mapOf("hafta" to hafta), cevirici = Alisveris.serializer())

    suspend fun kurallar() = cagir("GET", "kurallar", cevirici = KuralCevap.serializer())

    suspend fun kuralEkle(kural: String) = cagir(
        "POST", "kurallar", govde = buildJsonObject { put("kural", kural) }.toString(), cevirici = KuralCevap.serializer(),
    )

    suspend fun kuralSil(kural: String) = cagir(
        "POST", "kurallar/sil", govde = buildJsonObject { put("kural", kural) }.toString(), cevirici = KuralCevap.serializer(),
    )

    suspend fun sor(mesaj: String, ekler: List<Ek> = emptyList()) = cagir(
        "POST", "sohbet", govde = sohbetGovdesi(mesaj, ekler), cevirici = SohbetCevap.serializer(),
    )

    suspend fun soruyuBaslat(mesaj: String, ekler: List<Ek> = emptyList()) = cagir(
        "POST", "sohbet/baslat", govde = sohbetGovdesi(mesaj, ekler), cevirici = IsBaslat.serializer(),
    )

    suspend fun kesfiBaslat(konu: String) = cagir(
        "POST", "kesif/baslat", govde = buildJsonObject { put("konu", konu) }.toString(), cevirici = IsBaslat.serializer(),
    )

    suspend fun isDurumu(id: String) = cagir("GET", "is/$id", cevirici = IsDurumu.serializer())

    suspend fun sohbetGecmisi() = cagir("GET", "sohbet", cevirici = SohbetGecmisi.serializer())

    suspend fun tarifKesfet(konu: String) = cagir(
        "POST", "kesif", govde = buildJsonObject { put("konu", konu) }.toString(), cevirici = SohbetCevap.serializer(),
    )

    companion object {
        /** /sohbet gövdesi: {"mesaj": "...", "gorseller": [{"mime": "image/jpeg", "veri": base64}]} (app/api.py ChatIn). */
        fun sohbetGovdesi(mesaj: String, ekler: List<Ek>): String = buildJsonObject {
            put("mesaj", mesaj)
            put("gorseller", kotlinx.serialization.json.buildJsonArray {
                ekler.forEach { e -> add(buildJsonObject { put("mime", e.mime); put("veri", e.base64) }) }
            })
        }.toString()

        /** FastAPI hatası: {"detail": "metin"} ya da doğrulama hatalarında liste. */
        fun hataMetni(kod: Int, govde: String): String {
            val detay = runCatching { esnekJson.decodeFromString(HataCevap.serializer(), govde).detail }.getOrNull()
            val metin = when (detay) {
                is JsonPrimitive -> detay.content
                is JsonArray -> "Gönderilen bilgi eksik ya da hatalı."
                else -> null
            }
            return when (kod) {
                401 -> "Uygulama anahtarı geçersiz. Telegram'da /uygulama ile yeni bağlantı kodu al."
                503 -> metin ?: "Sunucu şu an hizmet veremiyor."
                in 500..599 -> "Sunucuda bir hata oldu ($kod). Biraz sonra tekrar dene."
                else -> metin ?: "İstek başarısız oldu ($kod)."
            }
        }
    }
}
