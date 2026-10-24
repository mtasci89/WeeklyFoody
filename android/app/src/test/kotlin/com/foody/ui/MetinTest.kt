package com.foody.ui

import com.foody.Ornek
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MetinTest {
    @Test fun sayilarVeTarihlerTurkce() {
        assertEquals("1.150", binlik(1150))
        assertEquals("~520 kcal", kcalMetni(520, true))
        assertEquals("610 kcal", kcalMetni(610, false))
        assertEquals("kalori ?", kcalMetni(null, null))
        assertEquals("19 Eki", kisaTarih("2026-10-19"))
    }

    @Test fun alisverisPaylasimiAlinanlariAtlar() {
        val liste = Ornek.alisveris
        val ilk = liste.gruplar.first().kalemler.first()
        val metin = alisverisMetni(liste, setOf(ilk.anahtar))
        assertTrue(metin.startsWith("🛒 Alışveriş listesi"))
        assertFalse(metin.lines().any { it == "- ${ilk.metin}" })
        assertTrue(metin.contains(liste.gruplar.last().kalemler.last().metin))
    }

    @Test fun tarifPaylasimiVeAdimlar() {
        val metin = tarifMetni(Ornek.tarif)
        assertTrue(metin.startsWith("Fırında Tavuk (2 kişilik)"))
        assertTrue(metin.contains("- 500 g tavuk"))
        assertEquals(listOf("Soğanı kavur.", "Etleri ekle!", "Pişir"), adimlar("Soğanı kavur. Etleri ekle!\nPişir"))
    }

    @Test fun seciliYemekTarihSlotVeHaftaylaGider() {
        val konu = SeciliOgun("2026-10-27", "Salı", "dinner_main", "Ana yemek", "Izgara Köfte", "gelecek_hafta")
        val metin = seciliMesaj(listOf(konu), YENILIKCI_ISTEK)
        assertTrue(metin.startsWith("Menüde seçtiğim yemek:\n- Salı Ana yemek (tarih=2026-10-27, slot=dinner_main, hafta=gelecek_hafta): Izgara Köfte"))
        assertTrue(metin.endsWith(YENILIKCI_ISTEK))
        assertTrue(YENILIKCI_ISTEK.contains("internet"))
        assertEquals("selam", seciliMesaj(emptyList(), "selam"))
    }

    @Test fun haftaKoduTariheGore() {
        val cumartesi = java.time.LocalDate.parse("2026-10-24")
        assertEquals("bu_hafta", haftaKodu("2026-10-19", cumartesi))
        assertEquals("gelecek_hafta", haftaKodu("2026-10-26", cumartesi))
        assertEquals("aktif", haftaKodu("2026-10-12", cumartesi))
        assertEquals("aktif", haftaKodu("bozuk", cumartesi))
    }

    @Test fun degisikliklerOkunurYazilir() {
        val sonuc = Ornek.isBitti.sonuc!!
        val plan = sonuc.menu!!.plan
        val satirlar = sonuc.degisiklikler.map { degisiklikMetni(it, plan) }
        assertEquals(listOf("Salı · Ana yemek: Izgara Balık → Izgara Köfte", "Mezeler: − Çoban Salata"), satirlar)
        val sali = plan!!.gunler[1].tarih
        assertEquals(setOf("$sali|dinner_main"), degisenAnahtarlar(sonuc.degisiklikler))
        assertEquals("Çar", kisaGun("Çarşamba"))
    }
}
