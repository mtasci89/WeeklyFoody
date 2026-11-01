package com.foody.ui

import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.dp
import com.foody.Ornek
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w320dp-h800dp-xhdpi")
class MenuAdlariTest {
    @get:Rule val kural = createAndroidComposeRule<ComponentActivity>()

    @Test fun uzunAnaYanVeMezeAdlariSecimdeDeKesilmez() {
        val ana = "Fesleğenli ve Közlenmiş Kırmızı Biber Soslu Fırında Hindi Köftesi"
        val yan = "Zeytinyağlı Brokoli ve Zencefilli Havuç Salatası"
        val meze = "Kinoa Krutonlu ve Fesleğenli Köz Patlıcan Mezesi"
        val original = Ornek.menu.plan!!
        val gun = original.gunler.first()
        val yemekler = listOf(
            gun.ogunler.first().copy(slot = "dinner_main", tarif = ana, yeni = true, kcal = 310),
            gun.ogunler.first().copy(slot = "dinner_side", tarif = yan, yeni = true, kcal = 155),
        )
        val menu = Ornek.menu.copy(kaloriGoster = true, plan = original.copy(
            gunler = listOf(gun.copy(ogunler = yemekler)),
            mezeler = listOf(yemekler.first().copy(slot = "hafta_meze_1", tarif = meze)),
        ))
        var secim by mutableStateOf<Set<String>?>(null)
        var tiklandi = false
        kural.setContent {
            FoodyTema {
                Column(Modifier.width(300.dp).verticalScroll(rememberScrollState()).padding(12.dp)) {
                    MenuTablosu(menu, secili = secim, tikla = { _, _ -> tiklandi = true })
                }
            }
        }
        fun adlariDogrula() {
            for (ad in listOf(ana, yan, meze)) {
                val layouts = mutableListOf<TextLayoutResult>()
                kural.onNodeWithText(ad, useUnmergedTree = true).performScrollTo()
                    .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
                assertTrue("Ad alt satıra geçmeli: $ad", layouts.single().lineCount > 1)
                assertFalse("Ad kesilmemeli: $ad", layouts.single().hasVisualOverflow)
                assertTrue((0 until layouts.single().lineCount).none { layouts.single().isLineEllipsized(it) })
            }
        }
        fun kaydet(ad: String) {
            val d = System.getenv("GORUNTU") ?: return
            kural.onNodeWithText(ana, useUnmergedTree = true).performScrollTo()
            kural.waitForIdle()
            val v = kural.activity.window.decorView
            val b = Bitmap.createBitmap(v.width, v.height, Bitmap.Config.ARGB_8888)
            v.draw(Canvas(b))
            File(d, ad).outputStream().use { b.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
        adlariDogrula()
        kaydet("4_tam_yemek_adlari.png")
        kural.runOnIdle { secim = setOf(degisimAnahtari(gun.tarih, "dinner_main")) }
        adlariDogrula()
        kural.onNodeWithText(ana).performScrollTo().performClick()
        assertTrue(tiklandi)
        kaydet("5_tam_adlar_coklu_secim.png")
    }
}
