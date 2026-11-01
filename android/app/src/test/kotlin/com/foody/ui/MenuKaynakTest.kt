package com.foody.ui

import android.app.Application
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ApplicationProvider
import com.foody.Ornek
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w411dp-h891dp-xxhdpi")
class MenuKaynakTest {
    @get:Rule val kural = createAndroidComposeRule<ComponentActivity>()

    @Test fun menuYemegindeGerekceVeGercekKaynakAcilir() {
        val gerekce = "Bu haftaki fırın yemeklerini çeşitlendirmek için; yanındaki sebzeyle uyumlu."
        val kaynak = "https://recipes.example/hindi-kapama"
        val old = Ornek.menu.plan!!
        val gun = old.gunler.first()
        val ogun = gun.ogunler.first().copy(kaynak = kaynak, neden = gerekce)
        val menu = Ornek.menu.copy(plan = old.copy(gunler = listOf(gun.copy(ogunler = listOf(ogun)))))
        val vm = AnaViewModel(ApplicationProvider.getApplicationContext<Application>()).also {
            it.ornekVeriyiYukle(menu, Ornek.alisveris, Ornek.tarifler.tarifler, Ornek.adaylar.tarifler, Ornek.kurallar, Ornek.tarif)
        }
        kural.setContent {
            FoodyTema { MenuEkran(vm, tarifAc = {}, ayarlar = {}, asistanaGit = {}) }
        }
        kural.onAllNodesWithTag("yemek_${ogun.slot}").onFirst().performClick()
        kural.onNodeWithText("NEDEN BU YEMEK?").assertExists()
        kural.onNodeWithText(gerekce).assertExists()
        kural.onNodeWithText("Tarifin kaynağını aç · recipes.example").performClick()
        val intent = shadowOf(kural.activity).nextStartedActivity
        assertEquals(Intent.ACTION_VIEW, intent.action)
        assertEquals(kaynak, intent.dataString)
        System.getenv("GORUNTU")?.let { folder ->
            kural.waitForIdle()
            val view = kural.activity.window.decorView
            val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888)
            view.draw(Canvas(bitmap))
            File(folder, "6_menu_tarif_kaynagi.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
    }
}
