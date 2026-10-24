package com.foody.ui

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

private val HAFTALAR = listOf("aktif" to "Aktif", "bu_hafta" to "Bu hafta", "gelecek_hafta" to "Gelecek hafta")

@Composable
fun MenuEkran(vm: AnaViewModel, tarifAc: (String) -> Unit, ayarlar: () -> Unit, asistanaGit: () -> Unit) {
    val durum by vm.menu.collectAsStateWithLifecycle()
    val ayar by vm.ayarlar.collectAsStateWithLifecycle()
    val hafta by vm.hafta.collectAsStateWithLifecycle()
    val isleniyor by vm.isleniyor.collectAsStateWithLifecycle()
    val tarifler by vm.tarifler.collectAsStateWithLifecycle()
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
            HAFTALAR.forEach { (kod, ad) -> FilterChip(selected = hafta == kod, onClick = { vm.haftaSec(kod) }, label = { Text(ad) }) }
        }
        DurumKarti(durum.yukleniyor && cevap == null, durum.hata, yenile = { vm.menuYenile() })
        if (cevap != null && plan == null) {
            Kart(Modifier.padding(16.dp).fillMaxWidth()) {
                Text("Bu hafta için menü yok.", fontWeight = FontWeight.Bold)
                Text(
                    "Menü her pazar kendiliğinden gelir. Beklemek istemezsen asistan kurallarına göre şimdi hazırlasın.",
                    color = Renk.Soluk, fontSize = 14.sp,
                )
                Button(onClick = { vm.asistanaSor(YENI_MENU_ISTEK); asistanaGit() }) { Text("Asistan hazırlasın") }
            }
        }
        if (plan != null) Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp)
                .testTag("menu_listesi"),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (cevap.kaloriSiniri != null) {
                Etiket("Öğün sınırı: kişi başı ${binlik(cevap.kaloriSiniri.toInt())} kcal", Renk.AcikTuruncu, Renk.Turuncu)
            }
            Kart(Modifier.fillMaxWidth()) {
                MenuTablosu(
                    cevap,
                    tikla = { gun, ogun -> if (plan.onaylanabilir) secilen = gun to ogun else tarifAc(ogun.tarifId) },
                    mezeEkle = if (plan.onaylanabilir) { { mezeEklenecek = true } } else null,
                )
            }
            if (plan.onaylanabilir) {
                Text(
                    "Bir yemeğe dokun: tarifini aç, değiştir, çıkar, o güne yemek ekle ya da asistan yerine yenilikçi bir şey bulsun. " +
                        "Daha büyük değişiklikleri Asistan'a yaz.",
                    color = Renk.Soluk, fontSize = 13.sp, lineHeight = 18.sp,
                )
                Button(onClick = { onaySor = true }, Modifier.fillMaxWidth(), enabled = !isleniyor) {
                    if (isleniyor) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else Text("Menüyü onayla")
                }
            } else {
                Text("Yemeğe dokun: tarifi ve malzemeleri.", color = Renk.Soluk, fontSize = 13.sp)
            }
        }
    }

    if (onaySor) AlertDialog(
        onDismissRequest = { onaySor = false },
        title = { Text("Menü onaylansın mı?") },
        text = { Text("Onaylanınca menü ve alışveriş listesi alıcılara Telegram'dan gönderilir. Sonra değiştirilemez.") },
        confirmButton = { TextButton(onClick = { onaySor = false; vm.menuyuOnayla() }) { Text("Onayla") } },
        dismissButton = { TextButton(onClick = { onaySor = false }) { Text("Vazgeç") } },
    )

    secilen?.let { (gun, ogun) ->
        val tarih = gun?.tarih ?: HAFTA
        val yer = gun?.gun ?: "Haftanın mezeleri"
        val konu = SeciliOgun(tarih, yer, ogun.slot, ogun.rol, ogun.tarif, hafta)
        AlertDialog(
            onDismissRequest = { secilen = null },
            title = { Text(ogun.tarif) },
            text = {
                OgunIslemleri(
                    yer = "$yer · ${ogun.rol}",
                    tarifiAc = { secilen = null; tarifAc(ogun.tarifId) },
                    yenilikci = { secilen = null; vm.yenilikciIste(konu); asistanaGit() },
                    asistanaYaz = {
                        secilen = null
                        vm.taslakAyarla(seciliMesaj(listOf(konu), ""))
                        asistanaGit()
                    },
                    listedenDegistir = { secilen = null; degisecek = gun to ogun },
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
) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(yer, color = Renk.Soluk, fontSize = 13.sp)
        IslemDugmesi("Tarifi aç", tarifiAc)
        IslemDugmesi("Asistan yerine yenilikçi bir şey koysun", yenilikci, vurgulu = true)
        IslemDugmesi("Asistana başka bir şey söyle", asistanaYaz)
        IslemDugmesi("Listeden değiştir", listedenDegistir)
        if (gunuEkle != null) IslemDugmesi("Bu güne yan yemek / çorba ekle", gunuEkle)
        IslemDugmesi("Menüden çıkar", cikar, tehlikeli = true)
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
