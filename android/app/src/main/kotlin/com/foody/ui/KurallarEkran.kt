package com.foody.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

private val ORNEK_KURALLAR = listOf(
    "Balık kullanma",
    "Kalorilerini de yaz yanına",
    "Bir kişi için bir öğün 1000 kaloriyi geçmesin",
    "Her akşam 3 farklı yemek olsun",
    "Protein ağırlıklı olsun",
)

@Composable
fun KurallarEkran(vm: AnaViewModel) {
    val durum by vm.kurallar.collectAsStateWithLifecycle()
    val isleniyor by vm.isleniyor.collectAsStateWithLifecycle()
    var yeni by rememberSaveable { mutableStateOf("") }
    val kurallar = durum.veri?.kurallar.orEmpty()

    Column(Modifier.fillMaxSize()) {
        Baslik("Kurallar", "Her menüde uygulanır, tekrar söylemene gerek yok")
        DurumKarti(durum.yukleniyor && durum.veri == null, durum.hata, yenile = { vm.kurallariYenile() })
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Kart(Modifier.fillMaxWidth()) {
                BolumBasligi("Ev kuralları")
                if (kurallar.isEmpty()) Text("Henüz kural yok.", color = Renk.Soluk)
                kurallar.forEachIndexed { i, kural ->
                    if (i > 0) HorizontalDivider(color = Renk.Cizgi)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(kural, Modifier.weight(1f), fontSize = 15.sp)
                        IconButton(onClick = { vm.kuralSil(kural) }, enabled = !isleniyor) {
                            Icon(Icons.Rounded.Close, contentDescription = "$kural kuralını sil", tint = Renk.Soluk)
                        }
                    }
                }
            }
            Kart(Modifier.fillMaxWidth()) {
                BolumBasligi("Yeni kural")
                OutlinedTextField(
                    yeni, { yeni = it }, Modifier.fillMaxWidth(),
                    placeholder = { Text("örn. Hafta içi 30 dakikadan uzun yemek olmasın") }, maxLines = 3,
                )
                Button(
                    onClick = { vm.kuralEkle(yeni); yeni = "" },
                    enabled = yeni.isNotBlank() && !isleniyor,
                ) { Text("Ekle") }
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ORNEK_KURALLAR.filter { it !in kurallar }.forEach { o ->
                        AssistChip(onClick = { yeni = o }, label = { Text(o, fontSize = 12.sp) })
                    }
                }
            }
            val ozet = durum.veri?.ozet.orEmpty()
            if (ozet.isNotEmpty()) Kart(Modifier.fillMaxWidth(), renk = Renk.AcikYesil) {
                BolumBasligi("Sistem ne yapıyor")
                ozet.forEach { Text("• $it", fontSize = 13.sp) }
            }
        }
    }
}
