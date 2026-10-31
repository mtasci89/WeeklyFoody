package com.foody.ui

import androidx.compose.material.icons.rounded.Share
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.TravelExplore
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.ui.platform.testTag
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.foody.data.TarifOzet

private val KATEGORILER = listOf(
    "" to "Hepsi", "main" to "Ana yemek", "meze" to "Meze", "salad" to "Salata", "side" to "Yan yemek", "soup" to "Çorba",
)

fun tarifAltYazisi(t: TarifOzet): String = listOfNotNull(
    t.kategoriAdi.ifBlank { null },
    t.kcal?.let { kcalMetni(it, t.tahmini) },
    t.sureDk?.let { "$it dk" },
    if (t.vejetaryen) "vejetaryen" else null,
).joinToString(" · ")

@Composable
fun TariflerEkran(vm: AnaViewModel, tarifAc: (String) -> Unit) {
    val durum by vm.tarifler.collectAsStateWithLifecycle()
    val menuTarifleri by vm.menuTarifleri.collectAsStateWithLifecycle()
    val baglam = androidx.compose.ui.platform.LocalContext.current
    val isleniyor by vm.isleniyor.collectAsStateWithLifecycle()
    // 0: onaylı menünün tarifleri, 1: kütüphane, 2: adaylar
    var sekme by rememberSaveable { mutableStateOf(0) }
    var ara by rememberSaveable { mutableStateOf("") }
    var kategori by rememberSaveable { mutableStateOf("") }
    var kesifPenceresi by rememberSaveable { mutableStateOf(false) }

    val kaynak = if (sekme == 2) durum.adaylar else durum.kutuphane
    val gorunen = kaynak.filter {
        (kategori.isBlank() || it.kategori == kategori) && (ara.isBlank() || it.ad.contains(ara.trim(), ignoreCase = true))
    }

    Column(Modifier.fillMaxSize()) {
        Baslik("Tarifler", "${durum.kutuphane.size} tarif · ${durum.adaylar.size} aday") {
            IconButton(onClick = { vm.tarifleriYenile() }) { Icon(Icons.Rounded.Refresh, contentDescription = "Yenile") }
        }
        TabRow(selectedTabIndex = sekme, containerColor = Renk.Arka, contentColor = Renk.Yesil) {
            Tab(sekme == 0, { sekme = 0 }, text = { Text("Bu hafta") })
            Tab(sekme == 1, { sekme = 1 }, text = { Text("Kütüphane") })
            Tab(sekme == 2, { sekme = 2 }, text = { Text("Adaylar (${durum.adaylar.size})") })
        }
        if (sekme == 0) {
            BuHaftaninTarifleri(menuTarifleri, tarifAc, yenile = { vm.menuYenile() }) { veri ->
                val ad = "Foody tarifler ${veri.haftaBaslangic?.let { kisaTarih(it) } ?: ""} haftası"
                runCatching {
                    pdfPaylas(baglam, ad, tarifSatirlari("Bu haftanın tarifleri", veri.haftaBaslangic?.let { "${kisaTarih(it)} haftası · onaylı menü" } ?: "", veri.tarifler))
                }.onFailure { vm.bilgiVer("PDF oluşturulamadı: ${it.message}") }
            }
            return@Column
        }
        DurumKarti(durum.yukleniyor && kaynak.isEmpty(), durum.hata, yenile = { vm.tarifleriYenile() })
        LazyColumn(
            Modifier.weight(1f),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (sekme == 2) item {
                Kart(Modifier.fillMaxWidth(), renk = Renk.AcikYesil) {
                    Text("Her gün internetten yeni tarifler", fontWeight = FontWeight.Bold)
                    Text(
                        "Asistan her sabah yemek sitelerinde ve sosyal medyada popüler olan 10 yeni tarifi kaynağıyla buraya ekler " +
                            "(kurallarına uyan, listende olmayanlar). Adaylar haftalık menüye \"yeni\" olarak girer; beğendiklerini listene eklersin. " +
                            "Menüye hiç girmeyen adaylar 30 gün sonra listeden kalkar.",
                        fontSize = 13.sp, color = Renk.Soluk,
                    )
                    if (durum.kesifSuruyor) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                        Text("Arıyorum… bir iki dakika sürebilir", fontSize = 13.sp)
                    } else Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { vm.gunlukKesif() }) { Text("Bugünün tariflerini getir") }
                        androidx.compose.material3.OutlinedButton(onClick = { kesifPenceresi = true }) {
                            Icon(Icons.Rounded.TravelExplore, contentDescription = null)
                            Text(" Konu ara")
                        }
                    }
                    durum.kesifSonucu?.let { Text(it, fontSize = 13.sp) }
                }
            }
            item {
                OutlinedTextField(ara, { ara = it }, Modifier.fillMaxWidth(), placeholder = { Text("Ada göre ara") }, singleLine = true)
            }
            item {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    KATEGORILER.forEach { (kod, ad) -> FilterChip(selected = kategori == kod, onClick = { kategori = kod }, label = { Text(ad) }) }
                }
            }
            items(gorunen, key = { it.id }) { t ->
                Kart(Modifier.fillMaxWidth(), tikla = { tarifAc(t.id) }) {
                    Text(t.ad, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                    Text(tarifAltYazisi(t), fontSize = 12.sp, color = Renk.Soluk)
                    if (t.aday) {
                        if (t.kaynak.isNotBlank()) Text("Kaynak: ${t.kaynak}", fontSize = 12.sp, color = Renk.Soluk, maxLines = 1)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(onClick = { vm.tarifiCikar(t.id) }, Modifier.weight(1f), enabled = !isleniyor) { Text("Çıkar") }
                            Button(onClick = { vm.tarifiOnayla(t.id) }, Modifier.weight(1f), enabled = !isleniyor) { Text("Listeye ekle") }
                        }
                    }
                }
            }
            if (gorunen.isEmpty() && !durum.yukleniyor) item {
                Text(
                    if (sekme == 2) "Onay bekleyen aday tarif yok." else "Eşleşen tarif yok.",
                    color = Renk.Soluk, modifier = Modifier.padding(8.dp),
                )
            }
        }
    }

    if (kesifPenceresi) {
        var konu by rememberSaveable { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { kesifPenceresi = false },
            title = { Text("Ne tür tarif arayayım?") },
            text = {
                OutlinedTextField(konu, { konu = it }, Modifier.fillMaxWidth(), placeholder = { Text("örn. pratik tavuk yemeği") }, singleLine = true)
            },
            confirmButton = {
                TextButton(onClick = { kesifPenceresi = false; vm.tarifKesfet(konu) }, enabled = konu.isNotBlank()) { Text("Ara") }
            },
            dismissButton = { TextButton(onClick = { kesifPenceresi = false }) { Text("Vazgeç") } },
        )
    }
}

/** Onaylı menünün tarifleri: her biri malzemeleriyle; hepsi tek PDF olarak paylaşılır. */
@Composable
private fun BuHaftaninTarifleri(
    durum: Yuk<com.foody.data.MenuTarifleri>,
    tarifAc: (String) -> Unit,
    yenile: () -> Unit,
    paylas: (com.foody.data.MenuTarifleri) -> Unit,
) {
    val veri = durum.veri
    DurumKarti(durum.yukleniyor && veri == null, durum.hata, yenile = yenile)
    if ((veri == null && !durum.yukleniyor && durum.hata == null) || (veri != null && veri.tarifler.isEmpty())) {
        Kart(Modifier.padding(16.dp).fillMaxWidth()) {
            Text("Onaylı menü yok.", fontWeight = FontWeight.Bold)
            Text("Menü > Taslak'ta menüyü onaylayınca tarifleri burada toplanır.", color = Renk.Soluk, fontSize = 14.sp)
        }
    }
    if (veri == null || veri.tarifler.isEmpty()) return
    LazyColumn(
        Modifier.fillMaxSize().testTag("menu_tarifleri"),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Button(onClick = { paylas(veri) }, Modifier.fillMaxWidth()) {
                Icon(androidx.compose.material.icons.Icons.Rounded.Share, contentDescription = null)
                androidx.compose.foundation.layout.Spacer(Modifier.size(8.dp))
                Text("Tüm tarifleri PDF olarak paylaş")
            }
        }
        items(veri.tarifler, key = { it.id }) { t ->
            Kart(Modifier.fillMaxWidth(), tikla = { tarifAc(t.id) }) {
                Text(t.gun, fontSize = 12.sp, color = Renk.Soluk, fontWeight = FontWeight.SemiBold)
                Text(t.ad, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                Text(
                    t.malzemeler.joinToString(", ") { listOf(it.miktar, it.ad).filter { s -> s.isNotBlank() }.joinToString(" ") },
                    fontSize = 13.sp, color = Renk.Soluk, maxLines = 3,
                    overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                )
            }
        }
    }
}
