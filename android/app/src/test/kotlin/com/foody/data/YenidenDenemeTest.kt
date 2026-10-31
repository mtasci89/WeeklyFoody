package com.foody.data

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.security.cert.CertificateException
import javax.net.ssl.SSLHandshakeException

/** Kullanıcı "5 kere sunucuya bağlanamadı" dedi: anlık kopmalar sessizce yeniden denenir. */
class YenidenDenemeTest {
    @Test fun baglantiKurulamadiysaHerIstekYenidenDenenir() {
        listOf(ConnectException("refused"), UnknownHostException("dns"), SocketTimeoutException("connect timed out")).forEach {
            assertTrue(Sunucu.tekrarDenenir("GET", it))
            assertTrue(Sunucu.tekrarDenenir("POST", it))
        }
    }

    @Test fun yoldaKopanYalnizcaOkumaIstegindeYenidenDenenir() {
        val koptu = IOException("unexpected end of stream")
        assertTrue(Sunucu.tekrarDenenir("GET", koptu))
        // Değişiklik iki kez uygulanmasın.
        assertFalse(Sunucu.tekrarDenenir("POST", koptu))
    }

    @Test fun cevapBeklerkenZamanAsimiVeSertifikaYenidenDenenmez() {
        assertFalse(Sunucu.tekrarDenenir("GET", SocketTimeoutException("timeout")))
        val pin = SSLHandshakeException("pin").apply { initCause(CertificateException("eşleşmiyor")) }
        assertFalse(Sunucu.tekrarDenenir("GET", pin))
        assertTrue(Sunucu.baglantiHatasi(pin).contains("sertifika"))
    }

    @Test fun sertifikaDisindakiTlsKopmasiBaglantiHatasidir() {
        val kopma = javax.net.ssl.SSLException("Connection reset")
        assertTrue(Sunucu.tekrarDenenir("GET", kopma))
        assertTrue(Sunucu.baglantiHatasi(kopma).contains("kez denendi"))
    }
}
