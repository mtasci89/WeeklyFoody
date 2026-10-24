package com.foody.data

import kotlinx.coroutines.delay
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class IsBaslat(@SerialName("is") val id: String, val durum: String = "calisiyor")

@Serializable
data class IsDurumu(
    @SerialName("is") val id: String,
    val durum: String,
    val sonuc: SohbetCevap? = null,
    val hata: String? = null,
)

/**
 * Asistan turu dakikalar sürebilir. Tek bir uzun bekleyen istek mobil ağda ya da uygulama arka
 * plana geçince kopuyordu ("Sunucuya ulaşılamadı") — oysa sunucu işi bitiriyordu. Burada iş
 * başlatılır, sonra kısa isteklerle sorulur; arada bağlantı koparsa sessizce yeniden denenir.
 */
object IsBekleyici {
    const val ARALIK_MS = 2_500L
    const val HATADA_ARALIK_MS = 5_000L
    const val EN_UZUN_MS = 12 * 60_000L

    suspend fun bekle(
        baslat: suspend () -> IsBaslat,
        durum: suspend (String) -> IsDurumu,
        /** Sunucu eskiyse (iş uçları yok, 404) cevabı tek istekte bekleyen eski yol. */
        eskiYol: suspend () -> SohbetCevap,
        saat: () -> Long = System::currentTimeMillis,
        uyu: suspend (Long) -> Unit = { delay(it) },
    ): SohbetCevap {
        val id = try {
            baslat().id
        } catch (e: Sunucu.Hata) {
            if (e.kod == 404) return eskiYol() else throw e
        }
        val bitis = saat() + EN_UZUN_MS
        var sonHata: Sunucu.Hata? = null
        while (true) {
            uyu(if (sonHata == null) ARALIK_MS else HATADA_ARALIK_MS)
            val d = try {
                durum(id).also { sonHata = null }
            } catch (e: Sunucu.Hata) {
                if (e.kod == 404) throw Sunucu.Hata("Asistanın işi kayboldu (sunucu yeniden başlamış olabilir). Tekrar dener misin?")
                sonHata = e
                if (saat() > bitis) throw e
                continue
            }
            when (d.durum) {
                "bitti" -> return d.sonuc ?: SohbetCevap(metin = "Asistan boş cevap döndü.", ok = false)
                "hata" -> throw Sunucu.Hata(d.hata ?: "Asistan bu isteği tamamlayamadı.")
            }
            if (saat() > bitis) throw Sunucu.Hata("Asistan 12 dakikadan uzun sürdü. Daha küçük parçalar halinde dener misin?")
        }
    }
}
