package com.foody.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Sunucu API'sinin (app/api.py) cevapları. Biçim değişirse önce
 * `tests/test_app_contract.py` kırılır; örnekler `src/test/resources/ornek/` altında.
 */
val esnekJson = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    coerceInputValues = true
}

@Serializable
data class DurumCevap(
    val ad: String = "",
    /** Sunucudaki kodun sürümü (kısa git sha) ve son değişikliğin başlığı. */
    val surum: String = "",
    val aciklama: String = "",
    val guncelleniyor: Boolean = false,
    val ajan: Boolean = false,
    val saglayici: String = "",
    val model: String = "",
    val kisi: Int = 4,
)

@Serializable
data class MenuCevap(
    @SerialName("kalori_goster") val kaloriGoster: Boolean = false,
    @SerialName("kalori_siniri") val kaloriSiniri: Double? = null,
    val kisi: Int = 4,
    val plan: Plan? = null,
    val mesaj: String? = null,
)

@Serializable
data class Plan(
    val id: String,
    @SerialName("hafta_baslangic") val haftaBaslangic: String,
    @SerialName("hafta_bitis") val haftaBitis: String,
    val durum: String,
    @SerialName("durum_metni") val durumMetni: String = "",
    val onaylanabilir: Boolean = false,
    val versiyon: Int = 0,
    val gunler: List<Gun> = emptyList(),
    /** Günlere bölünmeyen, haftalık meze listesi (tarih "HAFTA" ile değiştirilir). */
    val mezeler: List<Ogun> = emptyList(),
)

@Serializable
data class Gun(
    val tarih: String,
    val gun: String,
    val ogunler: List<Ogun> = emptyList(),
    @SerialName("toplam_kcal") val toplamKcal: Int? = null,
)

@Serializable
data class Ogun(
    val slot: String,
    val rol: String = "",
    @SerialName("tarif_id") val tarifId: String,
    val tarif: String,
    val kategori: String = "",
    val porsiyon: Int? = null,
    val degisti: Boolean = false,
    /** Kütüphanede olmayan, bu hafta denenecek yeni yemek (aday tarif). */
    val yeni: Boolean = false,
    val kcal: Int? = null,
    val protein: Int? = null,
    val tahmini: Boolean? = null,
)

@Serializable
data class TarifOzet(
    val id: String,
    val ad: String,
    val kategori: String = "",
    @SerialName("kategori_adi") val kategoriAdi: String = "",
    val durum: String = "approved",
    @SerialName("sure_dk") val sureDk: Int? = null,
    val vejetaryen: Boolean = false,
    val kaynak: String = "",
    val kcal: Int? = null,
    val protein: Int? = null,
    val tahmini: Boolean? = null,
) {
    val aday get() = durum == "candidate"
}

@Serializable
data class TarifListe(val tarifler: List<TarifOzet> = emptyList())

@Serializable
data class Malzeme(val miktar: String = "", val ad: String, val not: String = "")

@Serializable
data class TarifDetay(
    val id: String,
    val ad: String,
    val kategori: String = "",
    @SerialName("kategori_adi") val kategoriAdi: String = "",
    val durum: String = "approved",
    @SerialName("sure_dk") val sureDk: Int? = null,
    val vejetaryen: Boolean = false,
    val kaynak: String = "",
    val kcal: Int? = null,
    val protein: Int? = null,
    val tahmini: Boolean? = null,
    val porsiyon: Int = 4,
    val kisi: Int = 4,
    val malzemeler: List<Malzeme> = emptyList(),
    val hazirlanis: String = "",
    /** Menü tariflerinde: hangi gün ("Salı") ya da "Haftanın mezeleri". */
    val gun: String = "",
) {
    val aday get() = durum == "candidate"
}

/** Bir haftanın menüsündeki tariflerin hepsi (GET /menu/tarifler). */
@Serializable
data class MenuTarifleri(
    @SerialName("hafta_baslangic") val haftaBaslangic: String? = null,
    val durum: String? = null,
    val tarifler: List<TarifDetay> = emptyList(),
)

@Serializable
data class MesajCevap(val mesaj: String = "")

@Serializable
data class TarifIslemCevap(val mesaj: String = "", val tarif: TarifOzet? = null)

@Serializable
data class Alisveris(
    @SerialName("hafta_baslangic") val haftaBaslangic: String? = null,
    val gruplar: List<AlisverisGrubu> = emptyList(),
)

@Serializable
data class AlisverisGrubu(val kategori: String, val kalemler: List<Kalem> = emptyList())

@Serializable
data class Kalem(val anahtar: String, val ad: String = "", val metin: String)

@Serializable
data class KuralCevap(
    val kurallar: List<String> = emptyList(),
    val ozet: List<String> = emptyList(),
    val mesaj: String? = null,
    val eklendi: Boolean? = null,
)

@Serializable
data class SohbetCevap(
    val metin: String = "",
    val ok: Boolean = true,
    val araclar: List<String> = emptyList(),
    @SerialName("plan_degisti") val planDegisti: Boolean = false,
    @SerialName("kalori_ozeti") val kaloriOzeti: String = "",
    /** Asistan planı değiştirdiyse güncel menü ve değişenler. */
    val menu: MenuCevap? = null,
    val degisiklikler: List<Degisiklik> = emptyList(),
)

/** Asistan turunda değişen bir öğün. `tarih` ISO ya da "HAFTA"; eklenen için `eski`, çıkarılan için `yeni` boş. */
@Serializable
data class Degisiklik(val tarih: String, val slot: String, val eski: String? = null, val yeni: String? = null)

@Serializable
data class GecmisMesaj(val kullanici: Boolean, val metin: String)

@Serializable
data class SohbetGecmisi(val mesajlar: List<GecmisMesaj> = emptyList())

@Serializable
data class HataCevap(val detail: kotlinx.serialization.json.JsonElement? = null)
