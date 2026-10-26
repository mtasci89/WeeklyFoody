package com.foody.data

import java.util.Base64
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.*
import org.junit.Test

class CalTrackTest {
    @Test fun sadeceOkumaAnahtariPythonIleAyni() {
        val code = CalTrackKodu.olustur(Ayarlar.Degerler("https://example.com:8443", "t".repeat(40), "pin"))
        assertTrue(code.startsWith("FOODYCal1."))
        val body = esnekJson.parseToJsonElement(String(Base64.getUrlDecoder().decode(code.substringAfter('.')))).jsonObject
        assertEquals("56a8b00d057c531a15dc98e347597952cb8883b948a4aedd8d96fe5f3d5a3b6e", body["t"]!!.jsonPrimitive.content)
        assertEquals("https://example.com:8443", body["u"]!!.jsonPrimitive.content)
        assertFalse(body["t"]!!.jsonPrimitive.content == "t".repeat(40))
    }
}
