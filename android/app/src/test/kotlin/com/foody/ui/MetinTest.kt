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
}
