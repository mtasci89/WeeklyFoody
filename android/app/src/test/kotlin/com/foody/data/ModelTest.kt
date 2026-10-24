package com.foody.data

import com.foody.Ornek
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Sunucunun gerçek cevapları modellere eksiksiz oturuyor mu. */
class ModelTest {
    @Test fun menudeYeniYemekIsaretlidir() {
        val yeniler = Ornek.menu.plan!!.gunler.flatMap { it.ogunler }.filter { it.yeni }
        assertEquals(listOf("Tavuk Fajita"), yeniler.map { it.tarif })
    }

    @Test fun menuHaftanin7GununuVeOgunleriniOkur() {
        val m = Ornek.menu
        val plan = requireNotNull(m.plan)
        assertTrue(m.kaloriGoster)
        assertEquals(7, plan.gunler.size)
        assertEquals("Pazartesi", plan.gunler.first().gun)
        assertTrue(plan.onaylanabilir)
        val ogun = plan.gunler.first().ogunler.first()
        assertEquals("Ana yemek", ogun.rol)
        assertTrue(ogun.tarifId.isNotBlank() && ogun.slot.startsWith("dinner"))
        // Değeri bilinmeyen yemek null gelir, sıfır değil.
        assertTrue(plan.gunler.flatMap { it.ogunler }.any { it.kcal == null })
        assertTrue(plan.gunler.flatMap { it.ogunler }.any { it.kcal != null && it.tahmini == true })
    }

    @Test fun planYoksaNullGelir() {
        assertNull(Ornek.menuBos.plan)
    }

    @Test fun tarifListeleriVeDetay() {
        assertTrue(Ornek.tarifler.tarifler.size >= 10)
        assertTrue(Ornek.tarifler.tarifler.none { it.aday })
        val aday = Ornek.adaylar.tarifler.single()
        assertEquals("Tavuk Fajita", aday.ad)
        assertTrue(aday.aday)
        val t = Ornek.tarif
        assertEquals("Fırında Tavuk", t.ad)
        assertEquals(2, t.kisi)
        assertEquals(4, t.porsiyon)
        assertTrue(t.malzemeler.any { it.miktar == "500 g" && it.ad == "tavuk" })
    }

    @Test fun alisverisGruplari() {
        val a = Ornek.alisveris
        assertTrue(a.haftaBaslangic!!.matches(Regex("\\d{4}-\\d{2}-\\d{2}")))
        assertTrue(a.gruplar.isNotEmpty())
        val anahtarlar = a.gruplar.flatMap { g -> g.kalemler.map { it.anahtar } }
        assertEquals(anahtarlar.size, anahtarlar.toSet().size)
    }

    @Test fun kurallarVeOzet() {
        val k = Ornek.kurallar
        assertEquals(listOf("Balık kullanma", "Kalorilerini de yaz yanına", "Mutfakta az bulaşık çıksın"), k.kurallar)
        assertTrue(k.ozet.any { it.startsWith("Yalnızca ajana iletilir") })
    }

    @Test fun sohbetCevabi() {
        val s = Ornek.sohbet
        assertTrue(s.ok && s.planDegisti)
        assertTrue(s.kaloriOzeti.startsWith("🔥"))
        assertFalse(s.metin.isBlank())
    }

    @Test fun hataMetniSunucununAciklamasiniKullanir() {
        assertEquals("Bu kural bulunamadı.", Sunucu.hataMetni(404, Ornek.metin("ornek/hata.json")))
        assertTrue(Sunucu.hataMetni(401, "").contains("/uygulama"))
        assertTrue(Sunucu.hataMetni(500, "<html>").contains("500"))
        assertEquals("Gönderilen bilgi eksik ya da hatalı.", Sunucu.hataMetni(422, """{"detail":[{"msg":"x"}]}"""))
    }
}
