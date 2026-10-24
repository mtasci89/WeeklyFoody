package com.foody.ui

import android.app.Application
import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.core.app.ApplicationProvider
import com.foody.Ornek
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w411dp-h891dp-xxhdpi")
class GoruntuTest {
    @get:Rule val kural = createAndroidComposeRule<ComponentActivity>()

    @Test fun ekran() {
        val d = System.getenv("GORUNTU") ?: return
        val vm = AnaViewModel(ApplicationProvider.getApplicationContext<Application>())
        vm.ornekVeriyiYukle(Ornek.menu, Ornek.alisveris, Ornek.tarifler.tarifler, Ornek.adaylar.tarifler, Ornek.kurallar, Ornek.tarif)
        kural.setContent { FoodyTema { Uygulama(vm) } }
        fun kaydet(ad: String) {
            kural.waitForIdle()
            val v = kural.activity.window.decorView
            val b = Bitmap.createBitmap(v.width, v.height, Bitmap.Config.ARGB_8888)
            v.draw(Canvas(b))
            File(d, ad).outputStream().use { b.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
        kaydet("1_asistan.png")
        vm.asistanaSor("Salı'daki balık olmamış, daha yenilikçi bir şey koy. Çoban salatayı da meze listesinden çıkar.")
        kural.runOnIdle {
            vm.ornekCevap(Ornek.isBitti.sonuc!!.copy(metin = "Salı'ya balık yerine Izgara Köfte koydum; Çoban Salata'yı meze listesinden çıkardım."))
        }
        kaydet("2_taslak_degisiklik.png")
    }
}
