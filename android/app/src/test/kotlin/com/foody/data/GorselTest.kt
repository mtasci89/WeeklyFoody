package com.foody.data

import android.graphics.Bitmap
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.util.Base64

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class GorselTest {
    @Test fun buyukFotograflarOraniBozmadanKucultulur() {
        assertEquals(1600 to 1200, Gorsel.olcek(4000, 3000))
        assertEquals(900 to 1600, Gorsel.olcek(2250, 4000))
        assertEquals(800 to 600, Gorsel.olcek(800, 600)) // küçükse dokunulmaz
        assertEquals(240 to 180, Gorsel.olcek(1600, 1200, 240))
    }

    @Test fun sohbetGovdesiSunucununBekledigiBicimde() {
        val ek = Ek(1, byteArrayOf(1, 2, 3, 4), Bitmap.createBitmap(4, 4, Bitmap.Config.ARGB_8888))
        val govde = esnekJson.parseToJsonElement(Sunucu.sohbetGovdesi("bunları ekle", listOf(ek))).jsonObject

        assertEquals("bunları ekle", govde["mesaj"]!!.jsonPrimitive.content)
        val gorsel = govde["gorseller"]!!.jsonArray.single().jsonObject
        assertEquals("image/jpeg", gorsel["mime"]!!.jsonPrimitive.content)
        assertArrayEquals(byteArrayOf(1, 2, 3, 4), Base64.getDecoder().decode(gorsel["veri"]!!.jsonPrimitive.content))
    }

    @Test fun gorselsizGovdeBosListeTasir() {
        val govde = esnekJson.parseToJsonElement(Sunucu.sohbetGovdesi("selam", emptyList())).jsonObject
        assertEquals(0, govde["gorseller"]!!.jsonArray.size)
    }
}
