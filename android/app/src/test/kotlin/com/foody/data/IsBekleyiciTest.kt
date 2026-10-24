package com.foody.data

import com.foody.Ornek
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class IsBekleyiciTest {
    private val bitti = esnekJson.decodeFromString(IsDurumu.serializer(), Ornek.metin("ornek/is_bitti.json"))
    private val suruyor = esnekJson.decodeFromString(IsDurumu.serializer(), Ornek.metin("ornek/is_suruyor.json"))
    private val baslat = esnekJson.decodeFromString(IsBaslat.serializer(), Ornek.metin("ornek/is_baslat.json"))

    private class Saat(var ms: Long = 0) { val uykular = mutableListOf<Long>() }

    private fun bekle(cevaplar: List<() -> IsDurumu>, saat: Saat = Saat(), baslatma: () -> IsBaslat = { baslat }) = runBlocking {
        val sira = cevaplar.iterator()
        IsBekleyici.bekle(
            baslat = { baslatma() },
            durum = { sira.next()() },
            eskiYol = { SohbetCevap(metin = "eski yol") },
            saat = { saat.ms },
            uyu = { saat.uykular += it; saat.ms += it },
        )
    }

    @Test fun ornekCevaplarOkunur() {
        assertEquals("ornek-is", baslat.id)
        assertEquals("calisiyor", suruyor.durum)
        assertTrue(bitti.sonuc!!.planDegisti)
    }

    @Test fun bitenKadarSorarVeSonucuDondurur() {
        val saat = Saat()
        val sonuc = bekle(listOf({ suruyor }, { suruyor }, { bitti }), saat)
        assertEquals(bitti.sonuc, sonuc)
        assertEquals(List(3) { IsBekleyici.ARALIK_MS }, saat.uykular)
    }

    @Test fun baglantiKoparsaSessizceYenidenDener() {
        val saat = Saat()
        val sonuc = bekle(
            listOf({ throw Sunucu.Hata("Sunucuya ulaşılamadı.") }, { throw Sunucu.Hata("Sunucuya ulaşılamadı.") }, { bitti }),
            saat,
        )
        assertEquals(bitti.sonuc, sonuc)
        assertEquals(listOf(IsBekleyici.ARALIK_MS, IsBekleyici.HATADA_ARALIK_MS, IsBekleyici.HATADA_ARALIK_MS), saat.uykular)
    }

    @Test fun eskiSunucudaTekIstekleBekler() {
        val sonuc = bekle(emptyList(), baslatma = { throw Sunucu.Hata("Not Found", 404) })
        assertEquals("eski yol", sonuc.metin)
    }

    @Test fun baslatmaHatasiAynenIletilir() {
        val e = assertThrows(Sunucu.Hata::class.java) { bekle(emptyList(), baslatma = { throw Sunucu.Hata("Asistan kapalı", 503) }) }
        assertEquals("Asistan kapalı", e.message)
    }

    @Test fun kaybolanIsAnlasilirHataVerir() {
        val e = assertThrows(Sunucu.Hata::class.java) { bekle(listOf({ throw Sunucu.Hata("yok", 404) })) }
        assertTrue(e.message!!.contains("kayboldu"))
    }

    @Test fun sunucudakiHataGosterilir() {
        val e = assertThrows(Sunucu.Hata::class.java) { bekle(listOf({ IsDurumu("x", "hata", hata = "Gemini kotası doldu") })) }
        assertEquals("Gemini kotası doldu", e.message)
    }

    @Test fun cokUzunSurerseVazgecer() {
        val e = assertThrows(Sunucu.Hata::class.java) { bekle(List(400) { { suruyor } }) }
        assertTrue(e.message!!.contains("12 dakika"))
    }
}
