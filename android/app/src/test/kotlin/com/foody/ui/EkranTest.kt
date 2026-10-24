package com.foody.ui

import android.app.Application
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
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

    @Test fun menudenTumEkranlaraGezinme() {
        val vm = vm()
        kural.setContent { FoodyTema { Uygulama(vm) } }
        val plan = Ornek.menu.plan!!
        kural.onAllNodesWithText("Menü").assertCountEquals(2) // başlık + alt menü
        kural.onAllNodesWithText(plan.gunler.first().ogunler.first().tarif).onFirst().assertExists()
        kural.onNodeWithTag("menu_listesi").performScrollToNode(hasText("Menüyü onayla"))
        kural.onNodeWithText("Menüyü onayla").assertExists()

        kural.onNodeWithText("Alışveriş").performClick()
        val ilk = Ornek.alisveris.gruplar.first().kalemler.first()
        kural.onNodeWithText(ilk.metin).performClick()
        kural.onNodeWithTag("alisveris_listesi").performScrollToNode(hasText("İşaretleri temizle"))
        kural.onNodeWithText("İşaretleri temizle").assertExists()

        kural.onNodeWithText("Asistan").performClick()
        kural.onNodeWithText("Bir şey iste ya da sor…").assertExists()

        kural.onNodeWithText("Tarifler").performClick()
        kural.onNodeWithText("Adaylar (1)").performClick()
        kural.onNodeWithText("Tavuk Fajita").assertExists()
        kural.onNodeWithText("Listeye ekle").assertExists()

        kural.onNodeWithText("Kurallar").performClick()
        kural.onNodeWithText("Mutfakta az bulaşık çıksın").assertExists()
        kural.onNodeWithText("SİSTEM NE YAPIYOR").performScrollTo().assertExists()
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

    @Test fun menuYoksaAsistanaYonlendirir() {
        val vm = vm(menu = Ornek.menuBos)
        kural.setContent { FoodyTema { Uygulama(vm) } }
        kural.onNodeWithText("Bu hafta için menü yok.").assertExists()
        kural.onNodeWithText("Asistandan menü iste").performClick()
        // Yazı asistanın giriş alanına aktarılır (aynı metin öneri çipinde de var).
        kural.onNode(hasSetTextAction() and hasText("Gelecek hafta için yeni bir menü hazırla")).assertExists()
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
        kural.setContent { FoodyTema { AsistanEkran(vm, menuyeGit = {}) } }
        kural.onNodeWithContentDescription("Fotoğraf ekle").assertExists()
        kural.onNodeWithContentDescription("Fotoğrafı çıkar").assertExists()
        kural.onNodeWithText("Fotoğrafla ne yapayım? (örn. bunları ekle)").assertExists()
        kural.onNodeWithContentDescription("Gönder").assertIsEnabled().performClick()
        // Gönderilen fotoğraf sohbette görünür, bekleyen ek temizlenir.
        kural.onNodeWithContentDescription("Eklenen fotoğraf").assertExists()
        kural.onNodeWithContentDescription("Fotoğrafı çıkar").assertDoesNotExist()
    }

    @Test fun eklenenFotografCikarilabilir() {
        val vm = vm()
        vm.ornekEkle(com.foody.data.Ek(9, byteArrayOf(1), android.graphics.Bitmap.createBitmap(8, 8, android.graphics.Bitmap.Config.ARGB_8888)))
        kural.setContent { FoodyTema { AsistanEkran(vm, menuyeGit = {}) } }
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
        kural.setContent { FoodyTema { MenuEkran(vm, tarifAc = {}, ayarlar = {}, asistanaYaz = {}) } }
        kural.onNodeWithText("Aktif").assertIsSelected()
    }
}
