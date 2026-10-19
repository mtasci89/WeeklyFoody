package com.foody.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.SwapHoriz
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
fun MenuEkran(vm: AnaViewModel, tarifAc: (String) -> Unit, ayarlar: () -> Unit, asistanaYaz: (String) -> Unit) {
    val durum by vm.menu.collectAsStateWithLifecycle()
    val ayar by vm.ayarlar.collectAsStateWithLifecycle()
    val hafta by vm.hafta.collectAsStateWithLifecycle()
    val isleniyor by vm.isleniyor.collectAsStateWithLifecycle()
    val tarifler by vm.tarifler.collectAsStateWithLifecycle()
    val cevap = durum.veri
    val plan = cevap?.plan
    var degisecek by remember { mutableStateOf<Pair<Gun, Ogun>?>(null) }
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
                Text("Asistan kurallarına göre bir hafta kursun.", color = Renk.Soluk, fontSize = 14.sp)
                Button(onClick = { asistanaYaz("Gelecek hafta için yeni bir menü hazırla") }) { Text("Asistandan menü iste") }
            }
        }
        if (plan != null) {
            LazyColumn(
                Modifier.weight(1f).testTag("menu_listesi"),
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                if (cevap.kaloriSiniri != null) item {
                    Etiket("Öğün sınırı: kişi başı ${binlik(cevap.kaloriSiniri.toInt())} kcal", Renk.AcikTuruncu, Renk.Turuncu)
                }
                items(plan.gunler, key = { it.tarih }) { gun ->
                    GunKarti(
                        gun, cevap.kaloriGoster, cevap.kaloriSiniri,
                        degistirilebilir = plan.onaylanabilir,
                        tarifAc = tarifAc,
                        degistir = { degisecek = gun to it },
                    )
                }
                if (plan.onaylanabilir) item {
                    Button(onClick = { onaySor = true }, Modifier.fillMaxWidth(), enabled = !isleniyor) {
                        if (isleniyor) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else Text("Menüyü onayla")
                    }
                }
                item {
                    TextButton(onClick = { asistanaYaz("Menüde şunu değiştir: ") }, Modifier.fillMaxWidth()) {
                        Text("Asistana değişiklik söyle")
                    }
                }
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

    degisecek?.let { (gun, ogun) ->
        DegistirPenceresi(
            gun, ogun, tarifler.kutuphane,
            kapat = { degisecek = null },
            sec = { tarif -> degisecek = null; vm.ogunDegistir(gun.tarih, ogun.slot, tarif) },
        )
    }
}

@Composable
private fun GunKarti(
    gun: Gun,
    kaloriGoster: Boolean,
    sinir: Double?,
    degistirilebilir: Boolean,
    tarifAc: (String) -> Unit,
    degistir: (Ogun) -> Unit,
) {
    Kart(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(gun.gun, fontWeight = FontWeight.ExtraBold, fontSize = 16.sp, modifier = Modifier.weight(1f))
            Text(kisaTarih(gun.tarih), color = Renk.Soluk, fontSize = 13.sp)
        }
        if (gun.ogunler.isEmpty()) {
            Text("Boş gün (dışarıda yemek)", color = Renk.Soluk, fontSize = 14.sp)
        }
        gun.ogunler.forEachIndexed { i, ogun ->
            if (i > 0) HorizontalDivider(color = Renk.Cizgi)
            Row(Modifier.fillMaxWidth().clickable { tarifAc(ogun.tarifId) }.padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(ogun.rol, fontSize = 11.sp, color = Renk.Soluk, fontWeight = FontWeight.SemiBold)
                    Text(ogun.tarif, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
                if (kaloriGoster || ogun.kcal != null) Text(kcalMetni(ogun.kcal, ogun.tahmini), fontSize = 12.sp, color = Renk.Soluk)
                if (degistirilebilir) IconButton(onClick = { degistir(ogun) }) {
                    Icon(Icons.Rounded.SwapHoriz, contentDescription = "${ogun.tarif} değiştir", tint = Renk.Yesil)
                }
            }
        }
        val toplam = gun.toplamKcal
        if (kaloriGoster && gun.ogunler.isNotEmpty()) {
            val asti = toplam != null && sinir != null && toplam > sinir
            Etiket(
                if (toplam != null) "Kişi başı toplam ~${binlik(toplam)} kcal" else "Toplam kalori bilinmiyor",
                if (asti) Renk.AcikTuruncu else Renk.AcikYesil,
                if (asti) Renk.Kirmizi else Renk.Yesil,
            )
        }
    }
}

/** Bir öğünün yerine konabilecek tarifler: önce aynı türden olanlar. */
fun degisimAdaylari(ogun: Ogun, tarifler: List<TarifOzet>, ara: String): List<TarifOzet> {
    val ayniTur = tarifler.filter { it.kategori == ogun.kategori && it.id != ogun.tarifId }
    return ayniTur.ifEmpty { tarifler.filter { it.id != ogun.tarifId } }
        .filter { ara.isBlank() || it.ad.contains(ara.trim(), ignoreCase = true) }
}

@Composable
private fun DegistirPenceresi(gun: Gun, ogun: Ogun, tarifler: List<TarifOzet>, kapat: () -> Unit, sec: (String) -> Unit) {
    AlertDialog(
        onDismissRequest = kapat,
        title = { Text("${gun.gun} · ${ogun.rol}") },
        text = { DegistirIcerik(ogun, tarifler, sec) },
        confirmButton = {},
        dismissButton = { TextButton(onClick = kapat) { Text("Vazgeç") } },
    )
}

/** Pencerenin içeriği; testler pencere olmadan doğrudan bunu çizer. */
@Composable
fun DegistirIcerik(ogun: Ogun, tarifler: List<TarifOzet>, sec: (String) -> Unit) {
    var ara by rememberSaveable { mutableStateOf("") }
    val havuz = degisimAdaylari(ogun, tarifler, ara)
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("${ogun.tarif} yerine:", color = Renk.Soluk, fontSize = 13.sp)
        OutlinedTextField(ara, { ara = it }, Modifier.fillMaxWidth(), placeholder = { Text("Tarif ara") }, singleLine = true)
        // Pencere içinde tembel liste yerine sınırlı, düz bir liste: arama zaten daraltır.
        Column(Modifier.heightIn(max = 320.dp).verticalScroll(rememberScrollState())) {
            havuz.take(60).forEach { t ->
                Row(Modifier.fillMaxWidth().clickable { sec(t.ad) }.padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(t.ad, Modifier.weight(1f), fontSize = 15.sp)
                    if (t.kcal != null) Text(kcalMetni(t.kcal, t.tahmini), fontSize = 12.sp, color = Renk.Soluk)
                }
            }
            if (havuz.isEmpty()) Text("Uygun tarif bulunamadı.", color = Renk.Soluk)
        }
    }
}
