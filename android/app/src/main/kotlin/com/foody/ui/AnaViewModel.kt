package com.foody.ui

import android.app.Application
import android.net.Uri
import androidx.annotation.VisibleForTesting
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.foody.data.Alisveris
import com.foody.data.Ayarlar
import com.foody.data.BaglantiKodu
import com.foody.data.Degisiklik
import com.foody.data.DurumCevap
import com.foody.data.SohbetCevap
import com.foody.data.Ek
import com.foody.data.Gorsel
import com.foody.data.IsBekleyici
import com.foody.data.Isaretler
import com.foody.data.KuralCevap
import com.foody.data.MenuCevap
import com.foody.data.Plan
import com.foody.data.Sunucu
import com.foody.data.TarifDetay
import com.foody.data.TarifOzet
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class Yuk<T>(val yukleniyor: Boolean = false, val hata: String? = null, val veri: T? = null)

data class TarifDurumu(
    val yukleniyor: Boolean = false,
    val hata: String? = null,
    val kutuphane: List<TarifOzet> = emptyList(),
    val adaylar: List<TarifOzet> = emptyList(),
    /** Web'de tarif arama sürüyor mu ve son aramanın özeti. */
    val kesifSuruyor: Boolean = false,
    val kesifSonucu: String? = null,
)

data class SohbetMesaji(
    val kullanici: Boolean,
    val metin: String,
    /** Kullanıcının bu mesajla gönderdiği görsellerin önizlemeleri (yalnızca bu oturumda). */
    val gorseller: List<android.graphics.Bitmap> = emptyList(),
    val kaloriOzeti: String = "",
    val planDegisti: Boolean = false,
    val hata: Boolean = false,
    /** Asistan planı değiştirdiyse güncel menü ve neyin değiştiği (sohbette tablo olarak gösterilir). */
    val menu: MenuCevap? = null,
    val degisiklikler: List<Degisiklik> = emptyList(),
)

/** Menüde asistana konu edilen öğün. `tarih` ISO ya da haftalık meze listesi için "HAFTA". */
data class SeciliOgun(
    val tarih: String,
    val gun: String,
    val slot: String,
    val rol: String,
    val tarif: String,
    val hafta: String = "aktif",
)

/** Seçili yemekle birlikte gönderilecek yenilik isteği. */
const val YENILIKCI_ISTEK =
    "Bu olmamış. Yerine daha yenilikçi, sıradışı bir şey koy; tarif listesine ve internetteki tariflere bak, kurallarıma uy."

/** Hiçbir yemek seçili değilken haftanın tamamı için yenilik isteği. */
const val HAFTAYI_YENILE_ISTEK =
    "Bu haftanın menüsü fazla tanıdık. Birkaç öğünü daha yenilikçi, sıradışı yemeklerle değiştir; internetteki tariflere de bak, kurallarıma uy."

/** Asistana giden metin: seçili yemekler (tarih ve slotuyla) + kullanıcının yazdığı. */
fun seciliMesaj(secili: List<SeciliOgun>, metin: String): String {
    if (secili.isEmpty()) return metin
    val satirlar = secili.joinToString("\n") { "- ${it.gun} ${it.rol} (tarih=${it.tarih}, slot=${it.slot}, hafta=${it.hafta}): ${it.tarif}" }
    return "Menüde seçtiğim yemek:\n$satirlar\n\n$metin".trim()
}

/** Plan haftasının sunucudaki adı: içinde bulunduğumuz hafta "bu_hafta", sonrası "gelecek_hafta". */
fun haftaKodu(haftaBaslangic: String, bugun: java.time.LocalDate = java.time.LocalDate.now()): String {
    val pazartesi = bugun.with(java.time.DayOfWeek.MONDAY)
    val bas = runCatching { java.time.LocalDate.parse(haftaBaslangic) }.getOrNull() ?: return "aktif"
    return when {
        bas == pazartesi -> "bu_hafta"
        bas.isAfter(pazartesi) -> "gelecek_hafta"
        else -> "aktif"
    }
}

/**
 * Menü sekmesinin bölümü bu ve gelecek haftanın planından seçilir (sunucu eski olsa da çalışır):
 * "taslak" onay bekleyen plan (önce gelecek hafta), "onayli" onaylanmış plan (önce bu hafta).
 */
fun bolumSec(bolum: String, bu: MenuCevap?, gelecek: MenuCevap?): MenuCevap? {
    // Gelecek haftanın menüsü varsa (onaylı olsa bile) bitmekte olan haftanın eski taslağı
    // "Taslak" diye gösterilmez; kullanıcı onu çoktan geride bıraktı.
    val adaylar = if (bolum == "onayli") listOf(bu, gelecek)
    else if (gelecek?.plan != null) listOf(gelecek) else listOf(bu)
    val uyan = adaylar.firstOrNull { c ->
        val p = c?.plan
        p != null && (if (bolum == "onayli") !p.onaylanabilir && p.gunler.any { it.ogunler.isNotEmpty() } else p.onaylanabilir)
    }
    return uyan ?: (bu ?: gelecek)?.copy(plan = null, mesaj = null)
}

/** Taslakta son yapılan değişiklik: Menü > Taslak'ta üstte gösterilir, değişen yemekler vurgulanır. */
data class SonDegisiklik(val planId: String, val metin: String, val degisiklikler: List<Degisiklik>)

class AnaViewModel(app: Application) : AndroidViewModel(app) {
    private val ayarDeposu = Ayarlar(app)
    private val _ayarlar = MutableStateFlow(ayarDeposu.oku())
    val ayarlar: StateFlow<Ayarlar.Degerler> = _ayarlar.asStateFlow()

    private val sunucu = Sunucu { _ayarlar.value }
    private val isaretDeposu = Isaretler(app)

    /** Menü sekmesinin bölümü: "taslak" (onay bekleyen) ya da "onayli". */
    private val _hafta = MutableStateFlow("taslak")
    val hafta: StateFlow<String> = _hafta.asStateFlow()

    private val _menu = MutableStateFlow(Yuk<MenuCevap>())
    val menu: StateFlow<Yuk<MenuCevap>> = _menu.asStateFlow()

    private val _alisveris = MutableStateFlow(Yuk<Alisveris>())
    val alisveris: StateFlow<Yuk<Alisveris>> = _alisveris.asStateFlow()

    private val _isaretli = MutableStateFlow<Set<String>>(emptySet())
    val isaretli: StateFlow<Set<String>> = _isaretli.asStateFlow()

    private val _tarifler = MutableStateFlow(TarifDurumu())
    val tarifler: StateFlow<TarifDurumu> = _tarifler.asStateFlow()

    private val _tarif = MutableStateFlow(Yuk<TarifDetay>())
    val tarif: StateFlow<Yuk<TarifDetay>> = _tarif.asStateFlow()

    private val _kurallar = MutableStateFlow(Yuk<KuralCevap>())
    val kurallar: StateFlow<Yuk<KuralCevap>> = _kurallar.asStateFlow()

    private val _sohbet = MutableStateFlow<List<SohbetMesaji>>(emptyList())
    val sohbet: StateFlow<List<SohbetMesaji>> = _sohbet.asStateFlow()
    private val _asistanCalisiyor = MutableStateFlow(false)
    val asistanCalisiyor: StateFlow<Boolean> = _asistanCalisiyor.asStateFlow()
    /** Asistanın şu anki işinin başladığı an (geçen süreyi göstermek için). */
    private val _asistanBaslangic = MutableStateFlow(0L)
    val asistanBaslangic: StateFlow<Long> = _asistanBaslangic.asStateFlow()

    /** Asistana gönderilmeyi bekleyen fotoğraflar. */
    private val _ekler = MutableStateFlow<List<Ek>>(emptyList())
    val ekler: StateFlow<List<Ek>> = _ekler.asStateFlow()
    private var ekSayaci = 0L

    /** Bu ve gelecek haftanın menüsü (bölümler ve alışveriş/tarif kaynağı bunlardan seçilir). */
    private var haftalar: Pair<MenuCevap?, MenuCevap?> = null to null

    /** Onaylı menünün tarifleri (Tarifler > Bu hafta, PDF). */
    private val _menuTarifleri = MutableStateFlow(Yuk<com.foody.data.MenuTarifleri>())
    val menuTarifleri: StateFlow<Yuk<com.foody.data.MenuTarifleri>> = _menuTarifleri.asStateFlow()

    /** Alışveriş listesinin hangi menüden geldiği. */
    private val _alisverisKaynagi = MutableStateFlow("")
    val alisverisKaynagi: StateFlow<String> = _alisverisKaynagi.asStateFlow()

    /** Süren işlemin kullanıcıya görünen adı ("Yeni yemek hazırlanıyor…"). */
    private val _islemMetni = MutableStateFlow<String?>(null)
    val islemMetni: StateFlow<String?> = _islemMetni.asStateFlow()

    private val _sonDegisiklik = MutableStateFlow<SonDegisiklik?>(null)
    val sonDegisiklik: StateFlow<SonDegisiklik?> = _sonDegisiklik.asStateFlow()

    /** Asistan taslağı değiştirince Menü > Taslak'a geçilir (her değişiklikten sonra taslak görünsün). */
    private val _taslagaGit = kotlinx.coroutines.flow.MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val taslagaGit: kotlinx.coroutines.flow.SharedFlow<Unit> = _taslagaGit

    fun sonDegisiklikGoruldu() { _sonDegisiklik.value = null }

    /** Başka ekrandan asistanın yazı alanına hazır metin (ör. "Salı ana yemek için: "). */
    private val _taslak = MutableStateFlow("")
    val taslak: StateFlow<String> = _taslak.asStateFlow()

    private val _baglanti = MutableStateFlow(Yuk<DurumCevap>())
    val baglanti: StateFlow<Yuk<DurumCevap>> = _baglanti.asStateFlow()

    /** Kısa bilgi mesajı (snackbar). */
    private val _bilgi = MutableStateFlow<String?>(null)
    val bilgi: StateFlow<String?> = _bilgi.asStateFlow()

    /** Uzun süren bir işlem (onay, değiştirme) sürüyor mu. */
    private val _isleniyor = MutableStateFlow(false)
    val isleniyor: StateFlow<Boolean> = _isleniyor.asStateFlow()

    private var testModu = false

    init {
        if (_ayarlar.value.hazir) hepsiniYenile()
    }

    fun bilgiGosterildi() { _bilgi.value = null }
    fun taslakAyarla(metin: String) { _taslak.value = metin }
    fun taslakKullanildi() { _taslak.value = "" }

    /** Menüdeki bir yemek için asistandan daha yenilikçi bir şey ister. */
    fun yenilikciIste(o: SeciliOgun) = asistanaSor(seciliMesaj(listOf(o), YENILIKCI_ISTEK))

    private fun bildir(metin: String) { _bilgi.value = metin }
    fun bilgiVer(metin: String) = bildir(metin)

    fun hepsiniYenile() {
        menuYenile() // alışveriş listesi ve menü tarifleri de buradan yenilenir
        tarifleriYenile()
        kurallariYenile()
        gecmisiYukle()
    }

    // --- bağlantı ------------------------------------------------------------

    fun baglantiKoduKaydet(kod: String) {
        val degerler = runCatching { BaglantiKodu.coz(kod) }.getOrElse { e ->
            _baglanti.value = Yuk(hata = e.message)
            return
        }
        ayarDeposu.kaydet(degerler)
        _ayarlar.value = ayarDeposu.oku()
        baglantiyiDene(kayittanSonra = true)
    }

    fun baglantiyiDene(kayittanSonra: Boolean = false) {
        if (testModu) return
        viewModelScope.launch {
            _baglanti.value = Yuk(yukleniyor = true)
            runCatching { sunucu.durum() }
                .onSuccess {
                    _baglanti.value = Yuk(veri = it)
                    if (kayittanSonra) { bildir("Bağlandı. Hoş geldin!"); hepsiniYenile() }
                }
                .onFailure { _baglanti.value = Yuk(hata = it.message) }
        }
    }

    /** Sunucu güncellemesi sürüyor mu (düğmeyi kilitler, ilerleme gösterir). */
    private val _sunucuGuncelleniyor = MutableStateFlow(false)
    val sunucuGuncelleniyor: StateFlow<Boolean> = _sunucuGuncelleniyor.asStateFlow()

    fun sunucuyuGuncelle() {
        if (testModu || _sunucuGuncelleniyor.value) return
        viewModelScope.launch {
            _sunucuGuncelleniyor.value = true
            val onceki = _baglanti.value.veri?.surum ?: runCatching { sunucu.durum().surum }.getOrDefault("")
            val baslat = runCatching { sunucu.sunucuyuGuncelle() }
            baslat.onFailure { bildir(it.message ?: "Güncelleme başlatılamadı.") }
            baslat.onSuccess { c ->
                bildir(c.mesaj)
                // Bot yeniden başlarken birkaç kez ulaşılamaz; sürüm değişene ya da güncelleme bitene kadar bekle.
                var son: DurumCevap? = null
                repeat(36) {
                    kotlinx.coroutines.delay(5_000)
                    val d = runCatching { sunucu.durum() }.getOrNull() ?: return@repeat
                    son = d
                    _baglanti.value = Yuk(veri = d)
                    if (d.surum != onceki || (!d.guncelleniyor && it >= 2)) {
                        bildir(if (d.surum != onceki) "Sunucu güncellendi: ${d.surum}" else "Sunucu zaten güncel (${d.surum}).")
                        _sunucuGuncelleniyor.value = false
                        if (d.surum != onceki) hepsiniYenile()
                        return@launch
                    }
                }
                if (son == null) bildir("Sunucudan haber alınamadı; Telegram'a gelen mesaja bak.")
            }
            _sunucuGuncelleniyor.value = false
        }
    }

    fun baglantiyiKaldir() {
        ayarDeposu.kaydet(Ayarlar.Degerler())
        _ayarlar.value = ayarDeposu.oku()
        _baglanti.value = Yuk()
    }

    // --- menü ------------------------------------------------------------------

    fun haftaSec(hafta: String) {
        _hafta.value = hafta
        if (haftalar.first != null || haftalar.second != null) {
            _menu.value = Yuk(veri = bolumSec(hafta, haftalar.first, haftalar.second))
        }
        menuYenile()
    }

    /** Onaylı menünün haftası; yoksa taslağınki ("bu_hafta"/"gelecek_hafta"). */
    private fun kaynakHafta(): Pair<String, Boolean>? {
        val onayli = bolumSec("onayli", haftalar.first, haftalar.second)?.plan
        if (onayli != null) return haftaKodu(onayli.haftaBaslangic) to true
        val taslak = bolumSec("taslak", haftalar.first, haftalar.second)?.plan ?: return null
        return haftaKodu(taslak.haftaBaslangic) to false
    }

    fun menuYenile() {
        if (testModu || !_ayarlar.value.hazir) return
        viewModelScope.launch {
            _menu.update { it.copy(yukleniyor = true, hata = null) }
            runCatching { sunucu.menu("bu_hafta") to sunucu.menu("gelecek_hafta") }
                .onSuccess { (bu, gelecek) ->
                    haftalar = bu to gelecek
                    _menu.value = Yuk(veri = bolumSec(_hafta.value, bu, gelecek))
                    alisverisYenile()
                    menuTarifleriniYenile()
                }
                .onFailure { e -> _menu.update { it.copy(yukleniyor = false, hata = e.message) } }
        }
    }

    fun menuTarifleriniYenile() {
        if (testModu || !_ayarlar.value.hazir) return
        val onayli = bolumSec("onayli", haftalar.first, haftalar.second)?.plan
        if (onayli == null) { _menuTarifleri.value = Yuk(veri = com.foody.data.MenuTarifleri()); return }
        viewModelScope.launch {
            _menuTarifleri.update { it.copy(yukleniyor = true, hata = null) }
            runCatching { sunucu.menuTarifleri(haftaKodu(onayli.haftaBaslangic)) }
                .onSuccess { _menuTarifleri.value = Yuk(veri = it) }
                .onFailure { e ->
                    val metin = if ((e as? com.foody.data.Sunucu.Hata)?.kod == 404) "Bu özellik için sunucuyu güncelle (Ayarlar > Sunucuyu güncelle)." else e.message
                    _menuTarifleri.update { it.copy(yukleniyor = false, hata = metin) }
                }
        }
    }

    fun menuyuOnayla() {
        val plan = _menu.value.veri?.plan ?: return
        planiOnayla(plan)
    }

    /** Sohbetteki bir menü kartından Menü ekranına geçerken o kartın haftasını gösterir. */
    fun menuyuGoster(plan: Plan) {
        val bolum = if (plan.onaylanabilir) "taslak" else "onayli"
        if (_hafta.value != bolum || _menu.value.veri?.plan?.id != plan.id) haftaSec(bolum)
    }

    /** Düzenleme uçları için ekrandaki planın haftası ("bu_hafta"/"gelecek_hafta"). */
    private fun planHaftasi(): String = _menu.value.veri?.plan?.let { haftaKodu(it.haftaBaslangic) } ?: "aktif"

    /** Elle yapılan değişiklikten sonra: yeni menüyü göster, farkı vurgula. */
    private fun onbellegiGuncelle(cevap: MenuCevap) {
        val plan = cevap.plan ?: return
        haftalar = when {
            haftalar.first?.plan?.haftaBaslangic == plan.haftaBaslangic -> cevap to haftalar.second
            haftalar.second?.plan?.haftaBaslangic == plan.haftaBaslangic -> haftalar.first to cevap
            haftaKodu(plan.haftaBaslangic) == "gelecek_hafta" -> haftalar.first to cevap
            else -> cevap to haftalar.second
        }
    }

    private fun elleDegisti(cevap: MenuCevap, metin: String) {
        val eski = _menu.value.veri?.plan
        _menu.value = Yuk(veri = cevap)
        val yeni = cevap.plan ?: return
        onbellegiGuncelle(cevap)
        _hafta.value = if (yeni.onaylanabilir) "taslak" else "onayli"
        val fark = planFarki(eski?.takeIf { it.id == yeni.id }, yeni)
        if (fark.isNotEmpty()) _sonDegisiklik.value = SonDegisiklik(yeni.id, metin, fark)
    }

    /** Sohbetteki karttan onay: kartın haftası, ekranda hangi hafta açık olursa olsun. */
    fun planiOnayla(plan: Plan) = islem("Menü onaylanıyor…") {
        // Eski sunucularda da eski sohbet kartı başka bir sürümü sessizce onaylayamaz.
        val hafta = haftaKodu(plan.haftaBaslangic)
        val son = sunucu.menu(hafta)
        val guncel = son.plan
        if (guncel == null || guncel.id != plan.id || guncel.versiyon != plan.versiyon) {
            onbellegiGuncelle(son)
            _menu.value = Yuk(veri = son)
            throw Sunucu.Hata("Menü değişmiş. Son sürümü inceleyip tekrar onayla.", 409)
        }
        val cevap = sunucu.menuyuOnayla(hafta, plan.id, plan.versiyon)
        onbellegiGuncelle(cevap)
        // Eski sunucu Telegram'dan gönderdiğini söyleyebilir; uygulamada onay yalnızca kesinleştirir.
        bildir(cevap.mesaj?.takeIf { "Telegram" !in it } ?: "Menü onaylandı. Onaylı menü, tarifleri ve alışveriş listesi hazır.")
        _hafta.value = "onayli"
        menuYenile()
    }

    /** "Yerine yeni bir yemek bul": sohbet gerekmeden, kütüphanede olmayan bir yemek konur. */
    fun yenisiniBul(o: SeciliOgun, istek: String = "") = islem("Yeni yemek hazırlanıyor… (15-40 sn)") {
        val cevap = sunucu.yenisiniBul(o.tarih, o.slot, o.hafta, istek)
        val metin = cevap.mesaj.orEmpty().lines()
            .filterNot { "tarif_onayla" in it || it.isBlank() }
            .joinToString("\n").ifBlank { "${o.tarif} yerine yeni bir yemek kondu." }
        elleDegisti(cevap, metin)
        alisverisYenile()
    }

    fun ogunDegistir(tarih: String, slot: String, tarif: String) = islem {
        val cevap = sunucu.ogunDegistir(tarih, slot, tarif, planHaftasi())
        elleDegisti(cevap, "$tarif menüye kondu.")
        bildir("$tarif menüye kondu.")
        alisverisYenile()
    }

    fun ogunEkle(tarih: String, tarif: String) = islem {
        val cevap = sunucu.ogunEkle(tarih, tarif, planHaftasi())
        elleDegisti(cevap, cevap.mesaj ?: "$tarif eklendi.")
        bildir(cevap.mesaj ?: "$tarif eklendi.")
        alisverisYenile()
    }

    fun ogunCikar(tarih: String, slot: String, tarif: String) = islem {
        val cevap = sunucu.ogunCikar(tarih, slot, planHaftasi())
        elleDegisti(cevap, "$tarif çıkarıldı.")
        bildir("$tarif çıkarıldı.")
        alisverisYenile()
    }

    private fun islem(metin: String? = null, is_: suspend () -> Unit) {
        if (testModu) return
        viewModelScope.launch {
            _isleniyor.value = true
            _islemMetni.value = metin
            runCatching { is_() }.onFailure { e ->
                val m = if ((e as? Sunucu.Hata)?.kod == 404) "Bu özellik için sunucuyu güncelle (Ayarlar > Sunucuyu güncelle)." else e.message
                bildir(m ?: "İşlem başarısız.")
            }
            _isleniyor.value = false
            _islemMetni.value = null
        }
    }

    // --- alışveriş ---------------------------------------------------------------

    fun alisverisYenile() {
        if (testModu || !_ayarlar.value.hazir) return
        viewModelScope.launch {
            _alisveris.update { it.copy(yukleniyor = true, hata = null) }
            // Alışveriş listesi onaylı menüden gelir; onaylı menü yoksa taslaktan.
            val kaynak = kaynakHafta()
            _alisverisKaynagi.value = when (kaynak?.second) {
                true -> "Onaylı menünün listesi"
                false -> "Taslak menünün listesi (henüz onaylanmadı)"
                null -> ""
            }
            runCatching { sunucu.alisveris(kaynak?.first ?: "aktif") }
                .onSuccess {
                    _alisveris.value = Yuk(veri = it)
                    _isaretli.value = it.haftaBaslangic?.let(isaretDeposu::oku).orEmpty()
                }
                .onFailure { e -> _alisveris.update { it.copy(yukleniyor = false, hata = e.message) } }
        }
    }

    fun isaretle(anahtar: String) {
        val hafta = _alisveris.value.veri?.haftaBaslangic ?: return
        val yeni = _isaretli.value.let { if (anahtar in it) it - anahtar else it + anahtar }
        _isaretli.value = yeni
        isaretDeposu.yaz(hafta, yeni)
    }

    fun isaretleriTemizle() {
        val hafta = _alisveris.value.veri?.haftaBaslangic ?: return
        _isaretli.value = emptySet()
        isaretDeposu.yaz(hafta, emptySet())
    }

    // --- tarifler -----------------------------------------------------------------

    fun tarifleriYenile() {
        if (testModu || !_ayarlar.value.hazir) return
        viewModelScope.launch {
            _tarifler.update { it.copy(yukleniyor = true, hata = null) }
            runCatching { sunucu.tarifler(aday = false).tarifler to sunucu.tarifler(aday = true).tarifler }
                .onSuccess { (k, a) -> _tarifler.update { it.copy(yukleniyor = false, kutuphane = k, adaylar = a) } }
                .onFailure { e -> _tarifler.update { it.copy(yukleniyor = false, hata = e.message) } }
        }
    }

    fun tarifAc(id: String, kisi: Int = 0) {
        if (testModu) return
        viewModelScope.launch {
            _tarif.update { it.copy(yukleniyor = true, hata = null) }
            val kac = if (kisi > 0) kisi else (_menu.value.veri?.kisi ?: 4)
            runCatching { sunucu.tarif(id, kac) }
                .onSuccess { _tarif.value = Yuk(veri = it) }
                .onFailure { e -> _tarif.update { it.copy(yukleniyor = false, hata = e.message) } }
        }
    }

    fun tarifiOnayla(id: String) = islem {
        bildir(sunucu.tarifiOnayla(id).mesaj)
        tarifleriYenile()
        _tarif.value.veri?.takeIf { it.id == id }?.let { tarifAc(id, it.kisi) }
    }

    fun tarifiCikar(id: String) = islem {
        bildir(sunucu.tarifiCikar(id).mesaj)
        tarifleriYenile()
    }

    fun tarifKesfet(konu: String) {
        if (testModu || konu.isBlank()) return
        viewModelScope.launch {
            _tarifler.update { it.copy(kesifSuruyor = true, kesifSonucu = null) }
            runCatching {
                IsBekleyici.bekle(
                    baslat = { sunucu.kesfiBaslat(konu.trim()) },
                    durum = sunucu::isDurumu,
                    eskiYol = { sunucu.tarifKesfet(konu.trim()) },
                )
            }
                .onSuccess { c -> _tarifler.update { it.copy(kesifSuruyor = false, kesifSonucu = c.metin) }; tarifleriYenile() }
                .onFailure { e -> _tarifler.update { it.copy(kesifSuruyor = false, kesifSonucu = e.message) } }
        }
    }

    // --- kurallar -------------------------------------------------------------------

    fun kurallariYenile() {
        if (testModu || !_ayarlar.value.hazir) return
        viewModelScope.launch {
            _kurallar.update { it.copy(yukleniyor = true, hata = null) }
            runCatching { sunucu.kurallar() }
                .onSuccess { _kurallar.value = Yuk(veri = it) }
                .onFailure { e -> _kurallar.update { it.copy(yukleniyor = false, hata = e.message) } }
        }
    }

    fun kuralEkle(kural: String) = islem {
        val c = sunucu.kuralEkle(kural.trim())
        _kurallar.value = Yuk(veri = c)
        bildir(c.mesaj ?: "Kural eklendi.")
        menuYenile()
    }

    fun kuralSil(kural: String) = islem {
        val c = sunucu.kuralSil(kural)
        _kurallar.value = Yuk(veri = c)
        bildir("Kural silindi.")
        menuYenile()
    }

    // --- asistan ----------------------------------------------------------------------

    private fun gecmisiYukle() {
        if (testModu || !_ayarlar.value.hazir || _sohbet.value.isNotEmpty()) return
        viewModelScope.launch {
            runCatching { sunucu.sohbetGecmisi() }.onSuccess { g ->
                if (_sohbet.value.isEmpty()) _sohbet.value = g.mesajlar.map { SohbetMesaji(it.kullanici, it.metin) }
            }
        }
    }

    fun gorselEkle(uri: Uri) {
        if (_ekler.value.size >= Gorsel.EN_COK) { bildir("En fazla ${Gorsel.EN_COK} fotoğraf ekleyebilirsin."); return }
        val app = getApplication<Application>()
        viewModelScope.launch {
            runCatching { Gorsel.hazirla(app, uri, ++ekSayaci) }
                .onSuccess { ek -> _ekler.update { (it + ek).take(Gorsel.EN_COK) } }
                .onFailure { bildir("Fotoğraf okunamadı.") }
        }
    }

    fun ekiCikar(id: Long) = _ekler.update { liste -> liste.filterNot { it.id == id } }

    fun asistanaSor(metin: String) {
        val ekler = _ekler.value
        if ((metin.isBlank() && ekler.isEmpty()) || _asistanCalisiyor.value) return
        val soru = metin.trim()
        _sohbet.update { it + SohbetMesaji(true, soru, gorseller = ekler.map { e -> e.onizleme }) }
        _ekler.value = emptyList()
        if (testModu) return
        viewModelScope.launch {
            _asistanCalisiyor.value = true
            _asistanBaslangic.value = System.currentTimeMillis()
            runCatching {
                IsBekleyici.bekle(
                    baslat = { sunucu.soruyuBaslat(soru, ekler) },
                    durum = sunucu::isDurumu,
                    eskiYol = { sunucu.sor(soru, ekler) },
                )
            }
                .onSuccess { c ->
                    cevabiEkle(c)
                    if (c.planDegisti) { menuYenile(); alisverisYenile() }
                    // Asistan kural ya da tarif eklemiş olabilir.
                    kurallariYenile(); tarifleriYenile()
                }
                .onFailure { e -> _sohbet.update { it + SohbetMesaji(false, e.message ?: "Cevap alınamadı.", hata = true) } }
            _asistanCalisiyor.value = false
        }
    }

    private fun cevabiEkle(c: SohbetCevap) {
        _sohbet.update {
            it + SohbetMesaji(
                false, c.metin, kaloriOzeti = c.kaloriOzeti, planDegisti = c.planDegisti, hata = !c.ok,
                menu = c.menu, degisiklikler = c.degisiklikler,
            )
        }
        val plan = c.menu?.plan
        if (c.planDegisti && c.menu != null) onbellegiGuncelle(c.menu)
        if (c.planDegisti && plan != null && plan.onaylanabilir) {
            // Asistan taslağı değiştirdi: Menü > Taslak güncel hâliyle açılır, değişenler vurgulu.
            _hafta.value = "taslak"
            _menu.value = Yuk(veri = c.menu)
            _sonDegisiklik.value = SonDegisiklik(plan.id, c.metin, c.degisiklikler)
            _taslagaGit.tryEmit(Unit)
        } else if (c.planDegisti && plan != null && !plan.onaylanabilir) {
            // Asistan menüyü onayladı: Onaylı menü bölümüne geç.
            _hafta.value = "onayli"
            _menu.value = Yuk(veri = c.menu)
            menuYenile()
        }
    }

    // --- test kancası ------------------------------------------------------------------

    /** Ekran testleri için: asistanın bir cevabını sohbete ekler. */
    @VisibleForTesting
    fun ornekCevap(c: SohbetCevap) = cevabiEkle(c)

    /** Ekran testleri için: sunucuya gitmeden hazır veriyi gösterir. */
    @VisibleForTesting
    fun ornekEkle(ek: Ek) = _ekler.update { it + ek }

    @VisibleForTesting
    fun ornekVeriyiYukle(
        menu: MenuCevap?,
        alisveris: Alisveris?,
        kutuphane: List<TarifOzet>,
        adaylar: List<TarifOzet>,
        kurallar: KuralCevap?,
        tarif: TarifDetay?,
        ayarlar: Ayarlar.Degerler = Ayarlar.Degerler("https://1.2.3.4:8443", "x".repeat(40), "pin"),
        durum: DurumCevap? = null,
        menuTarifleri: com.foody.data.MenuTarifleri? = null,
    ) {
        testModu = true
        _baglanti.value = Yuk(veri = durum)
        _ayarlar.value = ayarlar
        _menu.value = Yuk(veri = menu)
        _menuTarifleri.value = Yuk(veri = menuTarifleri)
        if (alisveris != null) _alisverisKaynagi.value = "Onaylı menünün listesi"
        _alisveris.value = Yuk(veri = alisveris)
        _tarifler.value = TarifDurumu(kutuphane = kutuphane, adaylar = adaylar)
        _kurallar.value = Yuk(veri = kurallar)
        _tarif.value = Yuk(veri = tarif)
    }
}
