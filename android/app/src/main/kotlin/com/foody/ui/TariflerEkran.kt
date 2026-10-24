package com.foody.ui

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
    val isleniyor by vm.isleniyor.collectAsStateWithLifecycle()
    var sekme by rememberSaveable { mutableStateOf(0) }
    var ara by rememberSaveable { mutableStateOf("") }
    var kategori by rememberSaveable { mutableStateOf("") }
    var kesifPenceresi by rememberSaveable { mutableStateOf(false) }

    val kaynak = if (sekme == 0) durum.kutuphane else durum.adaylar
    val gorunen = kaynak.filter {
        (kategori.isBlank() || it.kategori == kategori) && (ara.isBlank() || it.ad.contains(ara.trim(), ignoreCase = true))
    }

    Column(Modifier.fillMaxSize()) {
        Baslik("Tarifler", "${durum.kutuphane.size} tarif · ${durum.adaylar.size} aday") {
            IconButton(onClick = { vm.tarifleriYenile() }) { Icon(Icons.Rounded.Refresh, contentDescription = "Yenile") }
        }
        TabRow(selectedTabIndex = sekme, containerColor = Renk.Arka, contentColor = Renk.Yesil) {
            Tab(sekme == 0, { sekme = 0 }, text = { Text("Kütüphane") })
            Tab(sekme == 1, { sekme = 1 }, text = { Text("Adaylar (${durum.adaylar.size})") })
        }
        DurumKarti(durum.yukleniyor && kaynak.isEmpty(), durum.hata, yenile = { vm.tarifleriYenile() })
        LazyColumn(
            Modifier.weight(1f),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (sekme == 1) item {
                Kart(Modifier.fillMaxWidth(), renk = Renk.AcikYesil) {
                    Text("Web'de yeni tarif ara", fontWeight = FontWeight.Bold)
                    Text(
                        "Asistan internette arar, bulduklarını kaynağıyla aday olarak ekler. Adaylar haftalık menüye \"yeni\" olarak girer; beğendiklerini listene eklersin.",
                        fontSize = 13.sp, color = Renk.Soluk,
                    )
                    if (durum.kesifSuruyor) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                        Text("Arıyorum… bir iki dakika sürebilir", fontSize = 13.sp)
                    } else Button(onClick = { kesifPenceresi = true }) {
                        Icon(Icons.Rounded.TravelExplore, contentDescription = null)
                        Text("  Tarif ara")
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
                    if (sekme == 1) "Onay bekleyen aday tarif yok." else "Eşleşen tarif yok.",
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
