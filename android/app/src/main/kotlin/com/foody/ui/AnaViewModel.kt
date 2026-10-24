package com.foody.ui

import android.app.Application
import android.net.Uri
import androidx.annotation.VisibleForTesting
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.foody.data.Alisveris
import com.foody.data.Ayarlar
import com.foody.data.BaglantiKodu
import com.foody.data.DurumCevap
import com.foody.data.Ek
import com.foody.data.Gorsel
import com.foody.data.IsBekleyici
import com.foody.data.Isaretler
import com.foody.data.KuralCevap
import com.foody.data.MenuCevap
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
)

/** Menüde asistana "bunlar hakkında" diye işaretlenen öğün. */
data class SeciliOgun(val tarih: String, val gun: String, val slot: String, val rol: String, val tarif: String)

/** Seçili yemeklerle birlikte gönderilecek yenilik isteği. */
const val YENILIKCI_ISTEK =
    "Bunlar olmamış. Yerlerine daha yenilikçi, sıradışı şeyler koy; tarif listesine ve internetteki tariflere bak, kurallarıma uy."

/** Hiçbir yemek seçili değilken haftanın tamamı için yenilik isteği. */
const val HAFTAYI_YENILE_ISTEK =
    "Bu haftanın menüsü fazla tanıdık. Birkaç öğünü daha yenilikçi, sıradışı yemeklerle değiştir; internetteki tariflere de bak, kurallarıma uy."

/** Asistana giden metin: seçili yemekler (tarih ve slotuyla) + kullanıcının yazdığı. */
fun seciliMesaj(secili: List<SeciliOgun>, metin: String): String {
    if (secili.isEmpty()) return metin
    val satirlar = secili.joinToString("\n") { "- ${it.gun} ${it.rol} (${it.tarih}, ${it.slot}): ${it.tarif}" }
    return "Seçtiğim yemekler:\n$satirlar\n\n$metin".trim()
}

class AnaViewModel(app: Application) : AndroidViewModel(app) {
    private val ayarDeposu = Ayarlar(app)
    private val _ayarlar = MutableStateFlow(ayarDeposu.oku())
    val ayarlar: StateFlow<Ayarlar.Degerler> = _ayarlar.asStateFlow()

    private val sunucu = Sunucu { _ayarlar.value }
    private val isaretDeposu = Isaretler(app)

    private val _hafta = MutableStateFlow("aktif")
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

    /** Menüde asistana konu olarak seçilen öğünler. */
    private val _secili = MutableStateFlow<List<SeciliOgun>>(emptyList())
    val secili: StateFlow<List<SeciliOgun>> = _secili.asStateFlow()

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
    fun ogunSec(o: SeciliOgun) = _secili.update { liste ->
        if (liste.any { it.tarih == o.tarih && it.slot == o.slot }) liste.filterNot { it.tarih == o.tarih && it.slot == o.slot }
        else liste + o
    }

    fun secimiTemizle() { _secili.value = emptyList() }

    private fun bildir(metin: String) { _bilgi.value = metin }

    fun hepsiniYenile() {
        menuYenile()
        alisverisYenile()
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
        _secili.value = emptyList()
        _hafta.value = hafta
        menuYenile()
        alisverisYenile()
    }

    fun menuYenile() {
        if (testModu || !_ayarlar.value.hazir) return
        viewModelScope.launch {
            _menu.update { it.copy(yukleniyor = true, hata = null) }
            runCatching { sunucu.menu(_hafta.value) }
                .onSuccess { _menu.value = Yuk(veri = it) }
                .onFailure { e -> _menu.update { it.copy(yukleniyor = false, hata = e.message) } }
        }
    }

    fun menuyuOnayla() = islem {
        val cevap = sunucu.menuyuOnayla(_hafta.value)
        _menu.value = Yuk(veri = cevap)
        bildir(cevap.mesaj ?: "Menü onaylandı.")
        alisverisYenile()
    }

    fun ogunDegistir(tarih: String, slot: String, tarif: String) = islem {
        val cevap = sunucu.ogunDegistir(tarih, slot, tarif)
        _menu.value = Yuk(veri = cevap)
        bildir("$tarif menüye kondu.")
        alisverisYenile()
    }

    private fun islem(is_: suspend () -> Unit) {
        if (testModu) return
        viewModelScope.launch {
            _isleniyor.value = true
            runCatching { is_() }.onFailure { bildir(it.message ?: "İşlem başarısız.") }
            _isleniyor.value = false
        }
    }

    // --- alışveriş ---------------------------------------------------------------

    fun alisverisYenile() {
        if (testModu || !_ayarlar.value.hazir) return
        viewModelScope.launch {
            _alisveris.update { it.copy(yukleniyor = true, hata = null) }
            runCatching { sunucu.alisveris(_hafta.value) }
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
        if ((metin.isBlank() && ekler.isEmpty() && _secili.value.isEmpty()) || _asistanCalisiyor.value) return
        val soru = seciliMesaj(_secili.value, metin.trim())
        _secili.value = emptyList()
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
                    _sohbet.update { it + SohbetMesaji(false, c.metin, kaloriOzeti = c.kaloriOzeti, planDegisti = c.planDegisti, hata = !c.ok) }
                    if (c.planDegisti) { menuYenile(); alisverisYenile() }
                    // Asistan kural ya da tarif eklemiş olabilir.
                    kurallariYenile(); tarifleriYenile()
                }
                .onFailure { e -> _sohbet.update { it + SohbetMesaji(false, e.message ?: "Cevap alınamadı.", hata = true) } }
            _asistanCalisiyor.value = false
        }
    }

    // --- test kancası ------------------------------------------------------------------

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
    ) {
        testModu = true
        _baglanti.value = Yuk(veri = durum)
        _ayarlar.value = ayarlar
        _menu.value = Yuk(veri = menu)
        _alisveris.value = Yuk(veri = alisveris)
        _tarifler.value = TarifDurumu(kutuphane = kutuphane, adaylar = adaylar)
        _kurallar.value = Yuk(veri = kurallar)
        _tarif.value = Yuk(veri = tarif)
    }
}
