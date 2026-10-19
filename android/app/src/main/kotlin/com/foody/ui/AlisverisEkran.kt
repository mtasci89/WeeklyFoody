package com.foody.ui

import android.content.Intent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Share
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.foody.data.Alisveris

/** Paylaşılacak düz metin: alınmamış kalemler kategori başlıklarıyla. */
fun alisverisMetni(liste: Alisveris, isaretli: Set<String>): String = buildString {
    append("🛒 Alışveriş listesi")
    liste.haftaBaslangic?.let { append(" (${kisaTarih(it)} haftası)") }
    liste.gruplar.forEach { g ->
        val kalan = g.kalemler.filter { it.anahtar !in isaretli }
        if (kalan.isNotEmpty()) {
            append("\n\n").append(g.kategori)
            kalan.forEach { append("\n- ").append(it.metin) }
        }
    }
}

@Composable
fun AlisverisEkran(vm: AnaViewModel) {
    val durum by vm.alisveris.collectAsStateWithLifecycle()
    val isaretli by vm.isaretli.collectAsStateWithLifecycle()
    val baglam = LocalContext.current
    val liste = durum.veri
    val toplam = liste?.gruplar?.sumOf { it.kalemler.size } ?: 0
    val alinan = liste?.gruplar?.sumOf { g -> g.kalemler.count { it.anahtar in isaretli } } ?: 0

    Column(Modifier.fillMaxSize()) {
        Baslik("Alışveriş", liste?.haftaBaslangic?.let { "${kisaTarih(it)} haftası · $alinan/$toplam alındı" }) {
            IconButton(onClick = { vm.alisverisYenile() }) { Icon(Icons.Rounded.Refresh, contentDescription = "Yenile") }
            if (liste != null && toplam > 0) IconButton(onClick = {
                val gonder = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, alisverisMetni(liste, isaretli))
                baglam.startActivity(Intent.createChooser(gonder, "Listeyi paylaş"))
            }) { Icon(Icons.Rounded.Share, contentDescription = "Paylaş") }
        }
        DurumKarti(durum.yukleniyor && liste == null, durum.hata, yenile = { vm.alisverisYenile() })
        if (liste != null && toplam == 0) {
            Kart(Modifier.padding(16.dp).fillMaxWidth()) {
                Text("Bu hafta için liste yok.", fontWeight = FontWeight.Bold)
                Text("Menü oluşunca malzemeler burada toplanır.", color = Renk.Soluk, fontSize = 14.sp)
            }
        }
        if (liste != null && toplam > 0) {
            LinearProgressIndicator(
                progress = { alinan.toFloat() / toplam }, Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                color = Renk.Yesil, trackColor = Renk.Cizgi,
            )
            LazyColumn(
                Modifier.weight(1f).testTag("alisveris_listesi"),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                items(liste.gruplar, key = { it.kategori }) { grup ->
                    Kart(Modifier.fillMaxWidth()) {
                        BolumBasligi(grup.kategori)
                        grup.kalemler.forEach { kalem ->
                            val alindi = kalem.anahtar in isaretli
                            Row(
                                Modifier.fillMaxWidth().clickable(role = Role.Checkbox) { vm.isaretle(kalem.anahtar) },
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Checkbox(checked = alindi, onCheckedChange = { vm.isaretle(kalem.anahtar) })
                                Text(
                                    kalem.metin, fontSize = 15.sp,
                                    color = if (alindi) Renk.Soluk else Renk.Murekkep,
                                    textDecoration = if (alindi) TextDecoration.LineThrough else null,
                                )
                            }
                        }
                    }
                }
                if (alinan > 0) item {
                    TextButton(onClick = { vm.isaretleriTemizle() }, Modifier.fillMaxWidth()) { Text("İşaretleri temizle") }
                }
            }
        }
    }
}
