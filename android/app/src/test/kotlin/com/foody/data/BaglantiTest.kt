package com.foody.data

import com.foody.Ornek
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.cert.CertificateException
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate

class BaglantiTest {
    private fun sertifika(ad: String): X509Certificate =
        CertificateFactory.getInstance("X.509").generateCertificate(Ornek.metin("tls/$ad").byteInputStream()) as X509Certificate

    @Test fun pythonunUrettigiKoduCozer() {
        val d = BaglantiKodu.coz(Ornek.metin("tls/kod.txt"))
        assertEquals("https://152.67.69.25:8443", d.adres)
        assertEquals("a".repeat(43), d.anahtar)
        assertEquals("UjXy+pin==", d.pin)
        assertTrue(d.hazir)
    }

    @Test fun kopyalarkenEklenenBosluklarSorunOlmaz() {
        val kod = Ornek.metin("tls/kod.txt")
        val bolunmus = " " + kod.substring(0, 20) + "\n" + kod.substring(20) + "\n"
        assertEquals(BaglantiKodu.coz(kod), BaglantiKodu.coz(bolunmus))
    }

    @Test fun bozukKodlarAnlasilirHataVerir() {
        val yanlis = assertThrows(IllegalArgumentException::class.java) { BaglantiKodu.coz("merhaba") }
        assertTrue(yanlis.message!!.contains("/uygulama"))
        val eksik = assertThrows(IllegalArgumentException::class.java) { BaglantiKodu.coz(Ornek.metin("tls/kod.txt").dropLast(30)) }
        assertTrue(eksik.message!!.contains("kopyala"))
    }

    @Test fun anahtarIziPythonlaAyni() {
        assertEquals(Ornek.metin("tls/sunucu.pin").trim(), SabitAnahtarGuveni.anahtarIzi(sertifika("sunucu.crt")))
    }

    @Test fun yalnizcaSabitlenenSertifikayaGuvenir() {
        val guven = SabitAnahtarGuveni(Ornek.metin("tls/sunucu.pin").trim())
        guven.checkServerTrusted(arrayOf(sertifika("sunucu.crt")), "ECDHE_ECDSA")
        assertThrows(CertificateException::class.java) {
            guven.checkServerTrusted(arrayOf(sertifika("baska.crt")), "ECDHE_ECDSA")
        }
        assertThrows(CertificateException::class.java) { guven.checkServerTrusted(emptyArray(), "ECDHE_ECDSA") }
    }
}
