package com.foody.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import kotlinx.serialization.Serializable
import java.util.Base64

/** Sunucu bağlantısı yalnızca telefonda, şifreli olarak saklanır. */
class Ayarlar(context: Context) {
    data class Degerler(
        /** Örn. https://152.67.69.25:8443 */
        val adres: String = "",
        /** Uygulama anahtarı (sunucudaki APP_API_TOKEN). */
        val anahtar: String = "",
        /** Sunucu sertifikasının açık anahtar parmak izi (SHA-256, base64). */
        val pin: String = "",
    ) {
        val hazir get() = adres.startsWith("https://") && anahtar.isNotBlank() && pin.isNotBlank()
    }

    private fun sifreli(context: Context): SharedPreferences = EncryptedSharedPreferences.create(
        DOSYA,
        MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC),
        context,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    /**
     * Telefonun anahtar kasası bozulursa şifreli dosya açılamaz; o zaman silinip yeniden kurulur ve
     * bağlantı kodunun yeniden girilmesi gerekir. Kasa hiç çalışmıyorsa değerler diske düz yazılmaz,
     * yalnızca uygulama açıkken bellekte tutulur.
     */
    private val prefs: SharedPreferences = runCatching { sifreli(context) }
        .recoverCatching {
            context.deleteSharedPreferences(DOSYA)
            sifreli(context)
        }
        .getOrElse { BellekPrefs() }

    fun oku() = Degerler(
        adres = prefs.getString("adres", "").orEmpty(),
        anahtar = prefs.getString("anahtar", "").orEmpty(),
        pin = prefs.getString("pin", "").orEmpty(),
    )

    fun kaydet(d: Degerler) {
        prefs.edit()
            .putString("adres", d.adres.trim().trimEnd('/'))
            .putString("anahtar", d.anahtar.trim())
            .putString("pin", d.pin.trim())
            .apply()
    }

    companion object {
        private const val DOSYA = "foody_ayarlar"
    }
}

/**
 * Telegram'daki /uygulama komutunun gönderdiği tek satırlık kod:
 * `FOODY1.` + base64url({"u": adres, "t": anahtar, "p": pin}). Sunucu tarafı: app/api_tls.py.
 */
object BaglantiKodu {
    private const val ON_EK = "FOODY1."

    @Serializable
    private data class Icerik(val u: String, val t: String, val p: String)

    fun coz(kod: String): Ayarlar.Degerler {
        val temiz = kod.trim().filterNot { it.isWhitespace() }
        require(temiz.startsWith(ON_EK)) { "Bu bir Foody bağlantı kodu değil. Telegram'da /uygulama yaz, gelen kodu yapıştır." }
        val icerik = runCatching {
            val govde = String(Base64.getUrlDecoder().decode(temiz.removePrefix(ON_EK)), Charsets.UTF_8)
            esnekJson.decodeFromString(Icerik.serializer(), govde)
        }.getOrElse { throw IllegalArgumentException("Kod eksik ya da bozuk kopyalanmış. Tamamını yeniden kopyala.") }
        require(icerik.u.startsWith("https://")) { "Koddaki adres https:// ile başlamıyor." }
        require(icerik.t.length >= 24 && icerik.p.isNotBlank()) { "Kod eksik kopyalanmış. Tamamını yeniden kopyala." }
        return Ayarlar.Degerler(adres = icerik.u.trimEnd('/'), anahtar = icerik.t, pin = icerik.p)
    }
}

/** Yalnızca bellekte duran, yazdıklarını diske koymayan basit SharedPreferences. */
private class BellekPrefs : SharedPreferences {
    private val harita = mutableMapOf<String, Any?>()
    override fun getAll(): Map<String, *> = harita.toMap()
    override fun getString(key: String, defValue: String?) = harita[key] as? String ?: defValue
    @Suppress("UNCHECKED_CAST")
    override fun getStringSet(key: String, defValues: Set<String>?) = harita[key] as? Set<String> ?: defValues
    override fun getInt(key: String, defValue: Int) = harita[key] as? Int ?: defValue
    override fun getLong(key: String, defValue: Long) = harita[key] as? Long ?: defValue
    override fun getFloat(key: String, defValue: Float) = harita[key] as? Float ?: defValue
    override fun getBoolean(key: String, defValue: Boolean) = harita[key] as? Boolean ?: defValue
    override fun contains(key: String) = key in harita
    override fun registerOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener?) {}
    override fun unregisterOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener?) {}
    override fun edit(): SharedPreferences.Editor = object : SharedPreferences.Editor {
        private val bekleyen = mutableMapOf<String, Any?>()
        private var temizle = false
        override fun putString(key: String, value: String?) = apply { bekleyen[key] = value }
        override fun putStringSet(key: String, values: Set<String>?) = apply { bekleyen[key] = values }
        override fun putInt(key: String, value: Int) = apply { bekleyen[key] = value }
        override fun putLong(key: String, value: Long) = apply { bekleyen[key] = value }
        override fun putFloat(key: String, value: Float) = apply { bekleyen[key] = value }
        override fun putBoolean(key: String, value: Boolean) = apply { bekleyen[key] = value }
        override fun remove(key: String) = apply { bekleyen[key] = null }
        override fun clear() = apply { temizle = true }
        override fun commit(): Boolean { apply(); return true }
        override fun apply() {
            if (temizle) harita.clear()
            bekleyen.forEach { (k, v) -> if (v == null) harita.remove(k) else harita[k] = v }
        }
    }
}
