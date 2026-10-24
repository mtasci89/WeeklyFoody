package com.foody.ui

import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Remove
import androidx.compose.material.icons.rounded.Share
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.foody.data.TarifDetay

/** Paylaşılacak düz metin. */
fun tarifMetni(t: TarifDetay): String = buildString {
    append(t.ad).append(" (").append(t.kisi).append(" kişilik)\n\nMalzemeler")
    t.malzemeler.forEach { m -> append("\n- ").append(listOf(m.miktar, m.ad).filter { it.isNotBlank() }.joinToString(" ")) }
    if (t.hazirlanis.isNotBlank()) append("\n\nHazırlanışı\n").append(t.hazirlanis)
    if (t.kaynak.startsWith("http")) append("\n\nKaynak: ").append(t.kaynak)
}

/** Hazırlanışı cümlelere bölüp adım adım gösterir. */
fun adimlar(metin: String): List<String> =
    metin.split(Regex("(?<=[.!?])\\s+|\\n+")).map { it.trim() }.filter { it.isNotEmpty() }

@Composable
fun TarifEkran(vm: AnaViewModel, id: String, geri: () -> Unit) {
    val durum by vm.tarif.collectAsStateWithLifecycle()
    val isleniyor by vm.isleniyor.collectAsStateWithLifecycle()
    val baglam = LocalContext.current
    LaunchedEffect(id) { if (durum.veri?.id != id) vm.tarifAc(id) }
    val t = durum.veri?.takeIf { it.id == id }

    Column(Modifier.fillMaxSize()) {
        Baslik(t?.ad ?: "Tarif", t?.let(::ozet), geri = geri) {
            if (t != null) IconButton(onClick = {
                val gonder = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, tarifMetni(t))
                baglam.startActivity(Intent.createChooser(gonder, "Tarifi paylaş"))
            }) { Icon(Icons.Rounded.Share, contentDescription = "Paylaş") }
        }
        DurumKarti(durum.yukleniyor && t == null, durum.hata, yenile = { vm.tarifAc(id) })
        if (t == null) return@Column
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (t.aday) Kart(Modifier.fillMaxWidth(), renk = Renk.Sari) {
                Text("Yeni tarif: menüye \"yeni\" olarak girebilir. Beğendiysen kalıcı listene ekle; sonraki haftalarda da seçilir.", fontSize = 14.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { vm.tarifiCikar(t.id); geri() }, Modifier.weight(1f), enabled = !isleniyor) { Text("Çıkar") }
                    Button(onClick = { vm.tarifiOnayla(t.id) }, Modifier.weight(1f), enabled = !isleniyor) { Text("Listeye ekle") }
                }
            }
            Kart(Modifier.fillMaxWidth()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        BolumBasligi("Malzemeler")
                        Text("Tarifin aslı ${t.porsiyon} kişilik", fontSize = 12.sp, color = Renk.Soluk)
                    }
                    IconButton(onClick = { vm.tarifAc(t.id, t.kisi - 1) }, enabled = t.kisi > 1) {
                        Icon(Icons.Rounded.Remove, contentDescription = "Kişi azalt")
                    }
                    Text("${t.kisi} kişi", fontWeight = FontWeight.Bold)
                    IconButton(onClick = { vm.tarifAc(t.id, t.kisi + 1) }, enabled = t.kisi < 30) {
                        Icon(Icons.Rounded.Add, contentDescription = "Kişi artır")
                    }
                }
                t.malzemeler.forEach { m ->
                    Row {
                        Text(m.miktar.ifBlank { "kararınca" }, Modifier.widthIn(min = 96.dp), fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                        Text(m.ad + if (m.not.isNotBlank()) " (${m.not})" else "", fontSize = 15.sp)
                    }
                }
            }
            if (t.hazirlanis.isNotBlank()) Kart(Modifier.fillMaxWidth()) {
                BolumBasligi("Hazırlanışı")
                adimlar(t.hazirlanis).forEachIndexed { i, adim ->
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("${i + 1}.", fontWeight = FontWeight.Bold, color = Renk.Yesil)
                        Text(adim, fontSize = 15.sp, lineHeight = 21.sp)
                    }
                }
            }
            if (t.kaynak.isNotBlank()) Text("Kaynak: ${t.kaynak}", fontSize = 12.sp, color = Renk.Soluk)
        }
    }
}

private fun ozet(t: TarifDetay): String = listOfNotNull(
    t.kategoriAdi.ifBlank { null },
    t.kcal?.let { kcalMetni(it, t.tahmini) + " / kişi" },
    t.protein?.let { "$it g protein" },
    t.sureDk?.let { "$it dk" },
).joinToString(" · ")
