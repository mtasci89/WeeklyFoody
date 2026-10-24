package com.foody.ui

import android.app.Application
import androidx.test.core.app.ApplicationProvider
import com.foody.Ornek
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** PDF içeriği. (Robolectric telefonun PdfDocument motorunu taklit etmiyor; dosya yazımı cihazda.) */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class PdfTest {
    private val baglam = ApplicationProvider.getApplicationContext<Application>()

    @Test fun menuPdfGunleriVeMezeleriIcerir() {
        val satirlar = menuSatirlari(Ornek.menu)
        val metinler = satirlar.map { it.toString() }
        assertTrue(metinler.first().contains("Haftalık menü"))
        assertTrue(metinler.any { it.contains("Taslak (henüz onaylanmadı)") })
        assertTrue(metinler.any { it.contains("Haftanın mezeleri") })
        assertTrue(satirlar.count { it is PdfSatiri.Bolum } >= 7)
    }

    @Test fun tarifPdfMalzemeVeAdimlariIcerirUzunsaSayfaBoler() {
        val tarifler = Ornek.menuTarifleri.tarifler
        val satirlar = tarifSatirlari("Bu haftanın tarifleri", "x", tarifler)
        assertTrue(satirlar.any { it is PdfSatiri.Ara && it.metin == "Malzemeler" })
        assertEquals(tarifler.size, satirlar.count { it is PdfSatiri.Bolum })
        // Hazırlanış numaralı adımlara bölünür.
        assertTrue(satirlar.any { it is PdfSatiri.Metin && it.metin.startsWith("1. ") })
    }

    @Test fun alisverisPdfAlinanlariAtlar() {
        val liste = Ornek.alisveris
        val ilk = liste.gruplar.first().kalemler.first()
        val satirlar = alisverisSatirlari(liste, setOf(ilk.anahtar))
        assertTrue(satirlar.none { it is PdfSatiri.Madde && it.metin.endsWith(ilk.metin) && it.metin.length == ilk.metin.length + 3 })
        assertTrue(satirlar.any { it is PdfSatiri.Bolum })
        assertEquals("Foody_menü_26_Eki_1_Kas", pdfAdi("Foody menü 26 Eki – 1 Kas"))
    }

    @Test fun taslakVeOnayliBolumlerDogruHaftayiSecer() {
        val taslak = Ornek.menu
        val onayli = taslak.copy(plan = taslak.plan!!.copy(onaylanabilir = false, durum = "APPROVED"))
        // Bu hafta onaylı, gelecek hafta taslak
        assertEquals(onayli, bolumSec("onayli", onayli, taslak))
        assertEquals(taslak, bolumSec("taslak", onayli, taslak))
        // Hiç onaylı yok
        assertNull(bolumSec("onayli", taslak, null)!!.plan)
        // Taslak yalnızca bu haftaysa
        assertEquals(taslak, bolumSec("taslak", taslak, null))
        // Gelecek hafta onaylıysa bu haftanın eski taslağı Taslak'ta görünmez
        assertNull(bolumSec("taslak", taslak, onayli)!!.plan)
    }
}
