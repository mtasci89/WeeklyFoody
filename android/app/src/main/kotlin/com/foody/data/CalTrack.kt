package com.foody.data

import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/** Only a derived, read-only credential is shared with Cal Track. */
object CalTrackKodu {
    @Serializable private data class Kod(val u: String, val t: String, val p: String)
    fun olustur(ayar: Ayarlar.Degerler): String {
        require(ayar.hazir)
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(ayar.anahtar.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        val token = mac.doFinal("foody-caltrack-read-v1".toByteArray()).joinToString("") { "%02x".format(it.toInt() and 255) }
        return "FOODYCal1." + Base64.getUrlEncoder().withoutPadding().encodeToString(
            esnekJson.encodeToString(Kod(ayar.adres, token, ayar.pin)).toByteArray(Charsets.UTF_8)
        )
    }
}

@Serializable
data class GunYemekleri(val tarih: String, val yemekler: List<GunYemegi> = emptyList())

@Serializable
data class GunYemegi(
    val id: String,
    val ad: String,
    val haftalik: Boolean = false,
    val kcal: Double? = null,
    val tahmini: Boolean? = null,
)
