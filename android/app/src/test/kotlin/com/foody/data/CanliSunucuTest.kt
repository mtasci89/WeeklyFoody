package com.foody.data

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Gerçek sunucuyla uçtan uca deneme: yalnızca FOODY_CANLI_KOD ortam değişkeni (bir bağlantı kodu)
 * verilirse çalışır, CI'da atlanır. Yerelde: sunucuyu örnek veriyle başlat, kodunu ver, testi çalıştır.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
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

    @Test fun fotografliMesajGider() = runBlocking {
        assumeTrue(kod != null)
        val ayar = BaglantiKodu.coz(kod!!)
        val ek = Ek(1, ByteArray(200_000) { (it % 251).toByte() }, android.graphics.Bitmap.createBitmap(2, 2, android.graphics.Bitmap.Config.ARGB_8888))
        val cevap = Sunucu { ayar }.sor("bunları ekle", listOf(ek))
        assertTrue(cevap.metin.isNotBlank())
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
