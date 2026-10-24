package com.foody

import com.foody.data.Alisveris
import com.foody.data.KuralCevap
import com.foody.data.MenuCevap
import com.foody.data.SohbetCevap
import com.foody.data.TarifDetay
import com.foody.data.TarifListe
import com.foody.data.esnekJson
import kotlinx.serialization.KSerializer

/**
 * Gerçek sunucu API'sinin cevapları (`python -m tests.app_samples ...` ile üretilir;
 * `tests/test_app_contract.py` API'nin hâlâ bu biçimi verdiğini denetler).
 */
object Ornek {
    fun metin(yol: String): String =
        requireNotNull(javaClass.classLoader?.getResource(yol)) { "Örnek bulunamadı: $yol" }.readText()

    private fun <T> oku(ad: String, s: KSerializer<T>): T = esnekJson.decodeFromString(s, metin("ornek/$ad.json"))

    val menu by lazy { oku("menu", MenuCevap.serializer()) }
    val menuBos by lazy { oku("menu_bos", MenuCevap.serializer()) }
    val tarifler by lazy { oku("tarifler", TarifListe.serializer()) }
    val adaylar by lazy { oku("adaylar", TarifListe.serializer()) }
    val tarif by lazy { oku("tarif", TarifDetay.serializer()) }
    val alisveris by lazy { oku("alisveris", Alisveris.serializer()) }
    val kurallar by lazy { oku("kurallar", KuralCevap.serializer()) }
    val durum by lazy { oku("durum", com.foody.data.DurumCevap.serializer()) }
    val sohbet by lazy { oku("sohbet", SohbetCevap.serializer()) }
}
