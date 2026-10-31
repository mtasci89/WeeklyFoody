package com.foody.ui

import androidx.compose.material.icons.rounded.CalendarMonth
import androidx.compose.material.icons.rounded.Share
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.MenuBook
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Checklist
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.RadioButtonUnchecked
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.foody.data.Gun
import com.foody.data.Ogun
import com.foody.data.TarifOzet

private val BOLUMLER = listOf("taslak" to "Taslak", "onayli" to "Onaylı menü")

@Composable
fun MenuEkran(vm: AnaViewModel, tarifAc: (String) -> Unit, ayarlar: () -> Unit, asistanaGit: () -> Unit, takvimAc: () -> Unit = {}) {
    val durum by vm.menu.collectAsStateWithLifecycle()
    val ayar by vm.ayarlar.collectAsStateWithLifecycle()
    val hafta by vm.hafta.collectAsStateWithLifecycle()
    val isleniyor by vm.isleniyor.collectAsStateWithLifecycle()
    val tarifler by vm.tarifler.collectAsStateWithLifecycle()
    val son by vm.sonDegisiklik.collectAsStateWithLifecycle()
    val islemMetni by vm.islemMetni.collectAsStateWithLifecycle()
    val secimModu by vm.secimModu.collectAsStateWithLifecycle()
    val secim by vm.secim.collectAsStateWithLifecycle()
    // null: kapalı; metin: toplu "yenileriyle değiştir" penceresindeki not.
    var topluNot by remember { mutableStateOf<String?>(null) }
    var topluCikar by remember { mutableStateOf(false) }
    val baglam = androidx.compose.ui.platform.LocalContext.current
    val cevap = durum.veri
    val plan = cevap?.plan
    var secilen by remember { mutableStateOf<Pair<Gun?, Ogun>?>(null) }
    var degisecek by remember { mutableStateOf<Pair<Gun?, Ogun>?>(null) }
    var eklenecek by remember { mutableStateOf<Gun?>(null) }
    var mezeEklenecek by remember { mutableStateOf(false) }
    var onaySor by rememberSaveable { mutableStateOf(false) }

    Column(Modifier.fillMaxSize()) {
        Baslik(
            "Menü",
            plan?.let { "${kisaTarih(it.haftaBaslangic)} – ${kisaTarih(it.haftaBitis)} · ${it.durumMetni}" },
        ) {
            if (plan != null && !isleniyor) IconButton(onClick = { if (secimModu) vm.secimiBitir() else vm.secimiBaslat() }) {
                Icon(
                    if (secimModu) Icons.Rounded.Close else Icons.Rounded.Checklist,
                    contentDescription = if (secimModu) "Seçimi kapat" else "Birden çok yemek seç",
                )
            }
            IconButton(onClick = takvimAc) { Icon(Icons.Rounded.CalendarMonth, "Yemek takvimi") }
            if (plan != null) IconButton(onClick = {
                val ad = "Foody menü ${kisaTarih(plan.haftaBaslangic)} – ${kisaTarih(plan.haftaBitis)}"
                runCatching { pdfPaylas(baglam, ad, menuSatirlari(cevap)) }.onFailure { vm.bilgiVer("PDF oluşturulamadı: ${it.message}") }
            }) { Icon(androidx.compose.material.icons.Icons.Rounded.Share, contentDescription = "PDF olarak paylaş") }
            if (ayar.hazir) IconButton(onClick = { vm.menuYenile() }) { Icon(Icons.Rounded.Refresh, contentDescription = "Yenile") }
            IconButton(onClick = ayarlar) { Icon(Icons.Rounded.Settings, contentDescription = "Ayarlar") }
        }
        if (!ayar.hazir) {
            Kart(Modifier.padding(16.dp).fillMaxWidth()) {
                Text("Foody'yi sunucuna bağla", fontWeight = FontWeight.Bold, fontSize = 17.sp)
                Text(
                    "Telegram'da botuna /uygulama yaz. Gelen bağlantı kodunu kopyalayıp Ayarlar'a yapıştır.",
                    color = Renk.Soluk, fontSize = 14.sp,
                )
                Button(onClick = ayarlar) { Text("Ayarlar'a git") }
            }
            return@Column
        }
        Row(
            Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            BOLUMLER.forEach { (kod, ad) -> FilterChip(selected = hafta == kod, onClick = { vm.haftaSec(kod) }, label = { Text(ad) }) }
        }
        DurumKarti(durum.yukleniyor && cevap == null, durum.hata, yenile = { vm.menuYenile() })
        if (cevap != null && plan == null) {
            Kart(Modifier.padding(16.dp).fillMaxWidth()) {
                if (hafta == "onayli") {
                    Text("Henüz onaylanmış menü yok.", fontWeight = FontWeight.Bold)
                    TextButton(onClick = { vm.haftaSec("taslak") }) { Text("Taslağa bak") }
                } else {
                    Text("Şu an onay bekleyen taslak yok.", fontWeight = FontWeight.Bold)
                    Text(
                        "Taslak her pazar kendiliğinden gelir. Beklemek istemezsen asistan kurallarına göre şimdi hazırlasın.",
                        color = Renk.Soluk, fontSize = 14.sp,
                    )
                    Button(onClick = { vm.asistanaSor(YENI_MENU_ISTEK); asistanaGit() }) { Text("Asistan hazırlasın") }
                    TextButton(onClick = { vm.haftaSec("onayli") }) { Text("Onaylı menüyü gör") }
                }
            }
        }
        if (plan != null) Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp)
                .testTag("menu_listesi"),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            islemMetni?.let { m ->
                Kart(Modifier.fillMaxWidth(), renk = Renk.Sari) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                        Text(m, fontSize = 14.sp)
                    }
                }
            }
            val bunun = son?.takeIf { it.planId == plan.id }
            if (bunun != null) Kart(Modifier.fillMaxWidth().testTag("son_degisiklik"), renk = Renk.AcikYesil) {
                Text("Son değişiklik", fontWeight = FontWeight.ExtraBold, fontSize = 15.sp, color = Renk.Yesil)
                if (bunun.metin.isNotBlank()) Text(bunun.metin, fontSize = 14.sp, lineHeight = 20.sp, color = Renk.Murekkep)
                DegisiklikListesi(bunun.degisiklikler, plan)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(onClick = asistanaGit) { Text("Asistana dön") }
                    TextButton(onClick = { vm.sonDegisiklikGoruldu() }) { Text("Tamam") }
                }
            }
            if (cevap.kaloriSiniri != null) {
                Etiket("Öğün sınırı: kişi başı ${binlik(cevap.kaloriSiniri.toInt())} kcal", Renk.AcikTuruncu, Renk.Turuncu)
            }
            Kart(Modifier.fillMaxWidth()) {
                MenuTablosu(
                    cevap,
                    degisen = bunun?.let { degisenAnahtarlar(it.degisiklikler) } ?: emptySet(),
                    tikla = { gun, ogun ->
                        if (isleniyor) Unit
                        else if (secimModu) vm.secimDegistir(degisimAnahtari(gun?.tarih ?: HAFTA, ogun.slot))
                        else secilen = gun to ogun
                    },
                    mezeEkle = if (!isleniyor && !secimModu) { { mezeEklenecek = true } } else null,
                    secili = if (secimModu) secim else null,
                    uzunBas = { gun, ogun ->
                        if (!isleniyor) {
                            val anahtar = degisimAnahtari(gun?.tarih ?: HAFTA, ogun.slot)
                            if (secimModu) vm.secimDegistir(anahtar) else vm.secimiBaslat(anahtar)
                        }
                    },
                )
            }
            if (plan.onaylanabilir) {
                Text(
                    if (secimModu) "Değiştirmek istediğin yemeklere dokun, sonra alttan ne yapılacağını seç."
                    else "Bir yemeğe dokun: tarifini aç, değiştir, çıkar ya da yerine yenilikçi bir şey bulunsun. " +
                        "Birden çok yemeği birlikte değiştirmek için yemeğe uzun bas ya da üstteki seçim simgesine dokun.",
                    color = Renk.Soluk, fontSize = 13.sp, lineHeight = 18.sp,
                )
                Button(onClick = { onaySor = true }, Modifier.fillMaxWidth(), enabled = !isleniyor) {
                    if (isleniyor) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else Text("Menüyü onayla")
                }
            } else {
                Text("Onaylı menü de düzenlenebilir. Yemeğe dokunup değiştir; yeni taslağı inceledikten sonra tekrar onayla.", color = Renk.Soluk, fontSize = 13.sp)
            }
        }
        if (plan != null && secimModu) SecimCubugu(
            sayi = secim.size,
            calisiyor = isleniyor,
            yenile = { topluNot = "" },
            asistanaYaz = { vm.secilenleriAsistanaYaz(); asistanaGit() },
            cikar = { topluCikar = true },
            vazgec = { vm.secimiBitir() },
        )
    }

    topluNot?.let { not ->
        AlertDialog(
            onDismissRequest = { topluNot = null },
            title = { Text("${secim.size} yemek yenileriyle değişsin") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        "Hepsi birlikte, birbirinden ve haftanın geri kalanından farklı olacak şekilde seçilir; " +
                            "yan yemekler o günün ana yemeğine uyar. İstersen bir not ekle.",
                        color = Renk.Soluk, fontSize = 13.sp,
                    )
                    OutlinedTextField(
                        not, { topluNot = it }, Modifier.fillMaxWidth().testTag("toplu_not"),
                        placeholder = { Text("ör. daha hafif olsun, biri balık olsun") },
                    )
                }
            },
            confirmButton = { TextButton(onClick = { topluNot = null; vm.secilenleriYenile(not.trim()) }) { Text("Değiştir") } },
            dismissButton = { TextButton(onClick = { topluNot = null }) { Text("Vazgeç") } },
        )
    }

    if (topluCikar) AlertDialog(
        onDismissRequest = { topluCikar = false },
        title = { Text("${secim.size} yemek menüden çıkarılsın mı?") },
        text = { Text(vm.seciliOgunler().joinToString("\n") { "${it.gun} · ${it.tarif}" }) },
        confirmButton = { TextButton(onClick = { topluCikar = false; vm.secilenleriCikar() }) { Text("Çıkar", color = Renk.Kirmizi) } },
        dismissButton = { TextButton(onClick = { topluCikar = false }) { Text("Vazgeç") } },
    )

    if (onaySor) AlertDialog(
        onDismissRequest = { onaySor = false },
        title = { Text("Menü onaylansın mı?") },
        text = { Text("Onaylanınca \"Onaylı menü\"ye geçer; tarifleri Tarifler'de, alışveriş listesi Alışveriş'te hazır olur ve PDF olarak paylaşabilirsin. Daha sonra düzenleyebilirsin; değişiklikler yeniden onay bekleyen taslağa dönüşür.") },
        confirmButton = { TextButton(onClick = { onaySor = false; vm.menuyuOnayla() }) { Text("Onayla") } },
        dismissButton = { TextButton(onClick = { onaySor = false }) { Text("Vazgeç") } },
    )

    secilen?.let { (gun, ogun) ->
        val tarih = gun?.tarih ?: HAFTA
        val yer = gun?.gun ?: "Haftanın mezeleri"
        val konu = SeciliOgun(tarih, yer, ogun.slot, ogun.rol, ogun.tarif, plan?.let { haftaKodu(it.haftaBaslangic) } ?: "aktif")
        AlertDialog(
            onDismissRequest = { secilen = null },
            title = { Text(ogun.tarif) },
            text = {
                OgunIslemleri(
                    yer = "$yer · ${ogun.rol}",
                    tarifiAc = { secilen = null; tarifAc(ogun.tarifId) },
                    yenilikci = { secilen = null; vm.yenisiniBul(konu) },
                    asistanaYaz = {
                        secilen = null
                        vm.taslakAyarla(seciliMesaj(listOf(konu), ""))
                        asistanaGit()
                    },
                    listedenDegistir = { secilen = null; degisecek = gun to ogun },
                    cokluSec = { secilen = null; vm.secimiBaslat(degisimAnahtari(tarih, ogun.slot)) },
                    gunuEkle = gun?.let { g -> { secilen = null; eklenecek = g } },
                    cikar = { secilen = null; vm.ogunCikar(tarih, ogun.slot, ogun.tarif) },
                )
            },
            confirmButton = {},
            dismissButton = { TextButton(onClick = { secilen = null }) { Text("Vazgeç") } },
        )
    }

    degisecek?.let { (gun, ogun) ->
        val havuz = tarifler.kutuphane + tarifler.adaylar
        SecimPenceresi(
            baslik = "${gun?.gun ?: "Haftanın mezeleri"} · ${ogun.rol}",
            kapat = { degisecek = null },
        ) { DegistirIcerik(ogun, havuz) { tarif -> degisecek = null; vm.ogunDegistir(gun?.tarih ?: HAFTA, ogun.slot, tarif) } }
    }

    eklenecek?.let { gun ->
        val havuz = (tarifler.kutuphane + tarifler.adaylar).filter { it.kategori in YAN_KATEGORILER }
        SecimPenceresi(baslik = "${gun.gun} günü ekle", kapat = { eklenecek = null }) {
            TarifSecici("Yan yemek, çorba ya da salata:", havuz) { tarif -> eklenecek = null; vm.ogunEkle(gun.tarih, tarif) }
        }
    }

    if (mezeEklenecek) {
        val havuz = (tarifler.kutuphane + tarifler.adaylar).filter { it.kategori == "meze" || it.kategori == "salad" }
        SecimPenceresi(baslik = "Haftanın mezelerine ekle", kapat = { mezeEklenecek = false }) {
            TarifSecici("Meze seç:", havuz) { tarif -> mezeEklenecek = false; vm.ogunEkle(HAFTA, tarif) }
        }
    }
}

const val YENI_MENU_ISTEK = "Bu hafta için kurallarıma göre yeni bir menü hazırla; birkaç yeni, sıradışı yemek de olsun."

private val YAN_KATEGORILER = setOf("side", "soup", "salad", "grain", "pasta", "pilaf")

/** Bir yemeğe dokununca çıkan seçenekler; testler pencere olmadan doğrudan bunu çizer. */
@Composable
fun OgunIslemleri(
    yer: String,
    tarifiAc: () -> Unit,
    yenilikci: () -> Unit,
    asistanaYaz: () -> Unit,
    listedenDegistir: () -> Unit,
    cikar: () -> Unit,
    gunuEkle: (() -> Unit)? = null,
    cokluSec: (() -> Unit)? = null,
) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(yer, color = Renk.Soluk, fontSize = 13.sp)
        IslemDugmesi("Tarifi aç", tarifiAc)
        IslemDugmesi("Yerine yepyeni bir yemek bul", yenilikci, vurgulu = true)
        if (cokluSec != null) IslemDugmesi("Birden çok yemek seç (birlikte değiştir)", cokluSec)
        IslemDugmesi("Asistana başka bir şey söyle", asistanaYaz)
        IslemDugmesi("Listeden değiştir", listedenDegistir)
        if (gunuEkle != null) IslemDugmesi("Bu güne yan yemek / çorba ekle", gunuEkle)
        IslemDugmesi("Menüden çıkar", cikar, tehlikeli = true)
    }
}

/** Çoklu seçim açıkken ekranın altındaki işlem çubuğu; testler doğrudan bunu çizer. */
@Composable
fun SecimCubugu(
    sayi: Int,
    calisiyor: Boolean,
    yenile: () -> Unit,
    asistanaYaz: () -> Unit,
    cikar: () -> Unit,
    vazgec: () -> Unit,
) {
    val etkin = sayi > 0 && !calisiyor
    Column(
        Modifier.fillMaxWidth().background(Renk.AcikTuruncu).padding(horizontal = 16.dp, vertical = 8.dp).testTag("secim_cubugu"),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                if (sayi == 0) "Değiştirmek istediğin yemeklere dokun" else "$sayi yemek seçili",
                Modifier.weight(1f), fontWeight = FontWeight.Bold, fontSize = 15.sp, color = Renk.Murekkep,
            )
            TextButton(onClick = vazgec) { Text("Vazgeç") }
        }
        Button(onClick = yenile, Modifier.fillMaxWidth(), enabled = etkin) { Text("Yenileriyle değiştir") }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            androidx.compose.material3.OutlinedButton(onClick = asistanaYaz, Modifier.weight(1f), enabled = etkin) { Text("Asistana yaz") }
            androidx.compose.material3.OutlinedButton(onClick = cikar, Modifier.weight(1f), enabled = etkin) {
                Text("Çıkar", color = if (etkin) Renk.Kirmizi else Renk.Soluk)
            }
        }
    }
}

@Composable
private fun IslemDugmesi(metin: String, tikla: () -> Unit, vurgulu: Boolean = false, tehlikeli: Boolean = false) {
    TextButton(onClick = tikla, Modifier.fillMaxWidth()) {
        Text(
            metin, Modifier.fillMaxWidth(), fontSize = 15.sp,
            fontWeight = if (vurgulu) FontWeight.Bold else FontWeight.Medium,
            color = if (tehlikeli) Renk.Kirmizi else Renk.Yesil,
        )
    }
}

@Composable
private fun SecimPenceresi(baslik: String, kapat: () -> Unit, icerik: @Composable () -> Unit) {
    AlertDialog(
        onDismissRequest = kapat,
        title = { Text(baslik) },
        text = icerik,
        confirmButton = {},
        dismissButton = { TextButton(onClick = kapat) { Text("Vazgeç") } },
    )
}

/** Bir öğünün yerine konabilecek tarifler: önce aynı türden olanlar. */
fun degisimAdaylari(ogun: Ogun, tarifler: List<TarifOzet>, ara: String): List<TarifOzet> {
    val ayniTur = tarifler.filter { it.kategori == ogun.kategori && it.id != ogun.tarifId }
    return ayniTur.ifEmpty { tarifler.filter { it.id != ogun.tarifId } }
        .filter { ara.isBlank() || it.ad.contains(ara.trim(), ignoreCase = true) }
}

/** Pencerenin içeriği; testler pencere olmadan doğrudan bunu çizer. */
@Composable
fun DegistirIcerik(ogun: Ogun, tarifler: List<TarifOzet>, sec: (String) -> Unit) {
    TarifSecici("${ogun.tarif} yerine:", tarifler.filter { it.id != ogun.tarifId }, ilkKategori = ogun.kategori, sec = sec)
}

/** Aranabilir tarif listesi; `ilkKategori` verilirse önce o türden olanlar. */
@Composable
fun TarifSecici(aciklama: String, tarifler: List<TarifOzet>, ilkKategori: String? = null, sec: (String) -> Unit) {
    var ara by rememberSaveable { mutableStateOf("") }
    val ayniTur = if (ilkKategori != null) tarifler.filter { it.kategori == ilkKategori } else emptyList()
    val havuz = ayniTur.ifEmpty { tarifler }.filter { ara.isBlank() || it.ad.contains(ara.trim(), ignoreCase = true) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(aciklama, color = Renk.Soluk, fontSize = 13.sp)
        OutlinedTextField(ara, { ara = it }, Modifier.fillMaxWidth(), placeholder = { Text("Tarif ara") }, singleLine = true)
        // Pencere içinde tembel liste yerine sınırlı, düz bir liste: arama zaten daraltır.
        Column(Modifier.heightIn(max = 320.dp).verticalScroll(rememberScrollState())) {
            havuz.take(60).forEach { t ->
                Row(Modifier.fillMaxWidth().clickable { sec(t.ad) }.padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(t.ad, Modifier.weight(1f), fontSize = 15.sp)
                    if (t.aday) Text("yeni ", fontSize = 11.sp, color = Renk.Turuncu, fontWeight = FontWeight.Bold)
                    if (t.kcal != null) Text(kcalMetni(t.kcal, t.tahmini), fontSize = 12.sp, color = Renk.Soluk)
                }
            }
            if (havuz.isEmpty()) Text("Uygun tarif bulunamadı.", color = Renk.Soluk)
        }
    }
}
