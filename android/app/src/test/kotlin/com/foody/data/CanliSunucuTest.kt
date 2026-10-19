package com.foody.data

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

/**
 * Gerçek sunucuyla uçtan uca deneme: yalnızca FOODY_CANLI_KOD ortam değişkeni (bir bağlantı kodu)
 * verilirse çalışır, CI'da atlanır. Yerelde: sunucuyu örnek veriyle başlat, kodunu ver, testi çalıştır.
 */
class CanliSunucuTest {
    private val kod: String? = System.getenv("FOODY_CANLI_KOD")

    @Test fun pinVeAnahtarlaBaglanirVeVeriyiOkur() = runBlocking {
        assumeTrue(kod != null)
        val ayar = BaglantiKodu.coz(kod!!)
        val sunucu = Sunucu { ayar }
        assertEquals("Foody", sunucu.durum().ad)
        assertNotNull(sunucu.menu().plan)
        assertTrue(sunucu.tarifler(aday = false).tarifler.isNotEmpty())
        assertTrue(sunucu.kurallar().kurallar.isNotEmpty())
        assertTrue(sunucu.alisveris().gruplar.isNotEmpty())
    }

    @Test fun yanlisPinleBaglanmaz() = runBlocking {
        assumeTrue(kod != null)
        val ayar = BaglantiKodu.coz(kod!!).copy(pin = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
        val hata = runCatching { Sunucu { ayar }.durum() }.exceptionOrNull()
        assertTrue(hata?.message.orEmpty().contains("sertifika"))
    }

    @Test fun yanlisAnahtarlaReddedilir() = runBlocking {
        assumeTrue(kod != null)
        val ayar = BaglantiKodu.coz(kod!!).copy(anahtar = "y".repeat(40))
        val hata = runCatching { Sunucu { ayar }.durum() }.exceptionOrNull()
        assertTrue(hata?.message.orEmpty().contains("/uygulama"))
    }
}
