package com.foody.ui

import android.app.Application
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.core.app.ApplicationProvider
import com.foody.Ornek
import com.foody.data.Ayarlar
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Tüm ekranların sunucunun gerçek cevaplarıyla çökmeden açıldığını ve gezinmenin çalıştığını denetler. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w411dp-h891dp-xxhdpi")
class EkranTest {
    @get:Rule val kural = createComposeRule()

    private fun vm(menu: com.foody.data.MenuCevap? = Ornek.menu) =
        AnaViewModel(ApplicationProvider.getApplicationContext<Application>()).also {
            it.ornekVeriyiYukle(
                menu = menu, alisveris = Ornek.alisveris, kutuphane = Ornek.tarifler.tarifler,
                adaylar = Ornek.adaylar.tarifler, kurallar = Ornek.kurallar, tarif = Ornek.tarif,
            )
        }

    @Test fun acilisAsistanSonraTumEkranlar() {
        val vm = vm()
        kural.setContent { FoodyTema { Uygulama(vm) } }
        // Ana ekran asistan: sohbet alanı ve güncel menünün tablosu.
        kural.onNodeWithText("Asistana yaz…").assertExists()
        kural.onNodeWithTag("menu_karti").assertExists()
        kural.onAllNodesWithText("Haftanın mezeleri").onFirst().assertExists()

        kural.onNodeWithText("Menü").performClick()
        val plan = Ornek.menu.plan!!
        kural.onNodeWithTag("menu_listesi").assertExists()
        kural.onAllNodesWithText(plan.gunler.first().ogunler.first().tarif).onFirst().assertExists()
        kural.onAllNodesWithText(plan.mezeler.first().tarif).onFirst().assertExists()
        kural.onNodeWithText("Menüyü onayla").performScrollTo().assertExists()

        kural.onNodeWithText("Alışveriş").performClick()
        val ilk = Ornek.alisveris.gruplar.first().kalemler.first()
        kural.onNodeWithText(ilk.metin).performClick()
        kural.onNodeWithTag("alisveris_listesi").performScrollToNode(hasText("İşaretleri temizle"))
        kural.onNodeWithText("İşaretleri temizle").assertExists()

        kural.onNodeWithText("Tarifler").performClick()
        kural.onNodeWithText("Adaylar (1)").performClick()
        kural.onNodeWithText("Tavuk Fajita").assertExists()
        kural.onNodeWithText("Listeye ekle").assertExists()

        kural.onNodeWithText("Kurallar").performClick()
        kural.onNodeWithText("Mutfakta az bulaşık çıksın").assertExists()
        kural.onNodeWithText("SİSTEM NE YAPIYOR").performScrollTo().assertExists()
    }

    @Test fun menudeMezelerGunlereBolunmez() {
        val plan = Ornek.menu.plan!!
        assert(plan.mezeler.isNotEmpty())
        assert(plan.gunler.flatMap { it.ogunler }.none { it.slot.contains("meze") })
        val vm = vm()
        kural.setContent { FoodyTema { MenuEkran(vm, tarifAc = {}, ayarlar = {}, asistanaGit = {}) } }
        kural.onNodeWithText("Haftanın mezeleri").assertExists()
        kural.onNodeWithContentDescription("Meze ekle").assertExists()
        kural.onNodeWithText("yeni").assertExists() // Tavuk Fajita: bu hafta denenecek
    }

    @Test fun asistaninDegistirdigiMenuSohbetteTabloOlarakGorunur() {
        val vm = vm()
        val sonuc = Ornek.isBitti.sonuc!!
        vm.ornekCevap(sonuc)
        val acilan = mutableListOf<String>()
        kural.setContent { FoodyTema { AsistanEkran(vm, menuyuAc = { acilan += it.haftaBaslangic }, ayarlar = {}) } }
        kural.onNodeWithText(sonuc.metin).assertExists()
        kural.onNodeWithText("DEĞİŞENLER").assertExists()
        kural.onNodeWithText("Salı · Ana yemek: Izgara Balık → Izgara Köfte").assertExists()
        kural.onNodeWithText("Mezeler: − Çoban Salata").assertExists()
        kural.onNodeWithText("Taslağı aç").performClick()
        assert(acilan == listOf(sonuc.menu!!.plan!!.haftaBaslangic))
        kural.onNodeWithText("Onayla").performClick()
        kural.onNodeWithText("Menü onaylansın mı?").assertExists()
    }

    @Test fun asistanTaslagiDegistirinceTaslakAcilirVeDegisenlerGorunur() {
        val vm = vm()
        kural.setContent { FoodyTema { Uygulama(vm) } }
        kural.onNodeWithText("Asistana yaz…").assertExists()
        val sonuc = Ornek.isBitti.sonuc!!
        kural.runOnIdle { vm.ornekCevap(sonuc) }
        // Kendiliğinden Menü > Taslak'a geçti; asistanın sözü ve değişenler üstte.
        kural.onNodeWithTag("son_degisiklik").assertExists()
        kural.onNodeWithText("Taslak").assertIsSelected()
        kural.onAllNodesWithText(sonuc.metin).onFirst().assertExists()
        kural.onAllNodesWithText("Salı · Ana yemek: Izgara Balık → Izgara Köfte").onFirst().assertExists()
        assert(vm.menu.value.veri == sonuc.menu)
        kural.onNodeWithText("Tamam").performClick()
        kural.onNodeWithTag("son_degisiklik").assertDoesNotExist()
    }

    @Test fun yemegeDokununcaAsistandanYenilikciIstenir() {
        val vm = vm()
        var asistan = 0
        kural.setContent { FoodyTema { MenuEkran(vm, tarifAc = {}, ayarlar = {}, asistanaGit = { asistan++ }) } }
        val gun = Ornek.menu.plan!!.gunler.first()
        val ogun = gun.ogunler.first()
        kural.onAllNodesWithTag("yemek_${ogun.slot}").onFirst().performClick()
        kural.onNodeWithText("Asistan yerine yenilikçi bir şey koysun").performClick()

        val giden = vm.sohbet.value.last().metin
        val hafta = haftaKodu(Ornek.menu.plan!!.haftaBaslangic)
        assert(giden.contains("tarih=${gun.tarih}, slot=${ogun.slot}, hafta=$hafta): ${ogun.tarif}")) { giden }
        assert(giden.endsWith(YENILIKCI_ISTEK))
        assert(asistan == 1)
    }

    @Test fun yemekIslemleriTumSecenekleriSunar() {
        val tiklanan = mutableListOf<String>()
        kural.setContent {
            FoodyTema {
                OgunIslemleri(
                    "Salı · Ana yemek",
                    tarifiAc = { tiklanan += "tarif" }, yenilikci = { tiklanan += "yeni" }, asistanaYaz = { tiklanan += "yaz" },
                    listedenDegistir = { tiklanan += "liste" }, cikar = { tiklanan += "cikar" },
                    gunuEkle = { tiklanan += "gun" },
                )
            }
        }
        listOf("Tarifi aç", "Asistana başka bir şey söyle", "Listeden değiştir", "Bu güne yan yemek / çorba ekle", "Menüden çıkar").forEach {
            kural.onNodeWithText(it).performClick()
        }
        assert(tiklanan == listOf("tarif", "yaz", "liste", "gun", "cikar"))
    }

    @Test fun tarifDetayiMalzemeleriVeAdimlariGosterir() {
        val vm = vm()
        kural.setContent { FoodyTema { TarifEkran(vm, Ornek.tarif.id, geri = {}) } }
        kural.onNodeWithText("Fırında Tavuk").assertExists()
        kural.onNodeWithText("500 g").assertExists()
        kural.onNodeWithText("2 kişi").assertExists()
        kural.onNodeWithContentDescription("Kişi artır").assertExists()
    }

    @Test fun ogunDegistirmeAyniTurdekiTarifleriOnerirVeSecer() {
        // Robolectric'te pencere (AlertDialog) içindeki metin alanı hiç durulmuyor; içerik ayrı çizilir.
        val ogun = Ornek.menu.plan!!.gunler.first().ogunler.first { it.kategori == "main" }
        val secilen = mutableListOf<String>()
        kural.setContent { FoodyTema { DegistirIcerik(ogun, Ornek.tarifler.tarifler) { secilen += it } } }
        kural.onNodeWithText("${ogun.tarif} yerine:").assertExists()
        val oneri = degisimAdaylari(ogun, Ornek.tarifler.tarifler, "")
        assert(oneri.isNotEmpty() && oneri.all { it.kategori == "main" && it.id != ogun.tarifId })
        kural.onNodeWithText(oneri.first().ad).performClick()
        assert(secilen == listOf(oneri.first().ad))
    }

    @Test fun menuYoksaAsistanHazirlar() {
        val vm = vm(menu = Ornek.menuBos)
        var asistan = 0
        kural.setContent { FoodyTema { MenuEkran(vm, tarifAc = {}, ayarlar = {}, asistanaGit = { asistan++ }) } }
        kural.onNodeWithText("Şu an onay bekleyen taslak yok.").assertExists()
        kural.onNodeWithText("Asistan hazırlasın").performClick()
        assert(vm.sohbet.value.last().metin == YENI_MENU_ISTEK)
        assert(asistan == 1)
    }

    @Test fun baglantiYoksaKurulumKartiCikar() {
        val vm = AnaViewModel(ApplicationProvider.getApplicationContext<Application>())
        vm.ornekVeriyiYukle(null, null, emptyList(), emptyList(), null, null, ayarlar = Ayarlar.Degerler())
        kural.setContent { FoodyTema { Uygulama(vm) } }
        kural.onNodeWithText("Foody'yi sunucuna bağla").assertExists()
        kural.onNodeWithText("Ayarlar'a git").performClick()
        kural.onNodeWithText("Kaydet ve bağlan").assertExists()
        kural.onNodeWithText("Henüz bağlı değil.").assertExists()
    }

    @Test fun asistanaFotografEklenipMetinsizGonderilebilir() {
        val vm = vm()
        vm.ornekEkle(com.foody.data.Ek(7, byteArrayOf(1), android.graphics.Bitmap.createBitmap(8, 8, android.graphics.Bitmap.Config.ARGB_8888)))
        kural.setContent { FoodyTema { AsistanEkran(vm, menuyuAc = {}, ayarlar = {}) } }
        kural.onNodeWithContentDescription("Fotoğraf ekle").assertExists()
        kural.onNodeWithContentDescription("Fotoğrafı çıkar").assertExists()
        kural.onNodeWithText("Fotoğrafla ne yapayım? (örn. bunları ekle)").assertExists()
        kural.onNodeWithContentDescription("Gönder").assertIsEnabled().performClick()
        // Bekleyen ek temizlenir; gönderilen fotoğraf sohbette görünür.
        kural.onNodeWithContentDescription("Fotoğrafı çıkar").assertDoesNotExist()
        kural.onNodeWithContentDescription("Eklenen fotoğraf").assertExists()
    }

    @Test fun eklenenFotografCikarilabilir() {
        val vm = vm()
        vm.ornekEkle(com.foody.data.Ek(9, byteArrayOf(1), android.graphics.Bitmap.createBitmap(8, 8, android.graphics.Bitmap.Config.ARGB_8888)))
        kural.setContent { FoodyTema { AsistanEkran(vm, menuyuAc = {}, ayarlar = {}) } }
        kural.onNodeWithContentDescription("Fotoğrafı çıkar").performClick()
        kural.onNodeWithContentDescription("Eklenen fotoğraf").assertDoesNotExist()
        kural.onNodeWithContentDescription("Gönder").assertIsNotEnabled()
    }

    @Test fun ayarlardaSunucuSurumuVeGuncellemeDugmesi() {
        val vm = AnaViewModel(ApplicationProvider.getApplicationContext<Application>())
        vm.ornekVeriyiYukle(null, null, emptyList(), emptyList(), null, null, durum = Ornek.durum)
        kural.setContent { FoodyTema { AyarlarEkran(vm, geri = {}) } }
        kural.onNodeWithText("Sürüm: ${Ornek.durum.surum}").assertExists()
        kural.onNodeWithText("Sunucuyu güncelle").performClick()
        kural.onNodeWithText("Sunucu güncellensin mi?").assertExists()
        kural.onNodeWithText("Vazgeç").performClick()
        kural.onNodeWithText("Sunucu güncellensin mi?").assertDoesNotExist()
    }

    @Test fun haftaSecimiVarsayilanAktif() {
        val vm = vm()
        kural.setContent { FoodyTema { MenuEkran(vm, tarifAc = {}, ayarlar = {}, asistanaGit = {}) } }
        kural.onNodeWithText("Taslak").assertIsSelected()
        kural.onNodeWithText("Onaylı menü").assertExists()
    }
}
