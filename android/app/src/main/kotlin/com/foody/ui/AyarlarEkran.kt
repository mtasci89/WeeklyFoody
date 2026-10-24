package com.foody.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import com.foody.BuildConfig

@Composable
fun AyarlarEkran(vm: AnaViewModel, geri: () -> Unit) {
    val ayar by vm.ayarlar.collectAsStateWithLifecycle()
    val baglanti by vm.baglanti.collectAsStateWithLifecycle()
    var kod by rememberSaveable { mutableStateOf("") }
    val guncelleniyor by vm.sunucuGuncelleniyor.collectAsStateWithLifecycle()
    var guncelleSor by rememberSaveable { mutableStateOf(false) }

    if (guncelleSor) AlertDialog(
        onDismissRequest = { guncelleSor = false },
        title = { Text("Sunucu güncellensin mi?") },
        text = { Text("Bot 1-3 dakika yeniden başlar; bu sırada asistan cevap vermez. Veritabanı önce yedeklenir.") },
        confirmButton = { TextButton(onClick = { guncelleSor = false; vm.sunucuyuGuncelle() }) { Text("Güncelle") } },
        dismissButton = { TextButton(onClick = { guncelleSor = false }) { Text("Vazgeç") } },
    )

    LaunchedEffect(Unit) { if (ayar.hazir && baglanti.veri == null && !baglanti.yukleniyor) vm.baglantiyiDene() }

    Column(Modifier.fillMaxSize()) {
        Baslik("Ayarlar", geri = geri)
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Kart(Modifier.fillMaxWidth()) {
                BolumBasligi("Sunucu bağlantısı")
                if (ayar.hazir) {
                    Text("Adres: ${ayar.adres}", fontSize = 14.sp)
                    when {
                        baglanti.yukleniyor -> Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp); Text("Deneniyor…", fontSize = 14.sp)
                        }
                        baglanti.veri != null -> {
                            val d = baglanti.veri!!
                            Text("✓ Bağlı", color = Renk.Yesil, fontWeight = FontWeight.Bold)
                            Text(
                                if (d.ajan) "Asistan açık (${d.model})" else "Asistan kapalı: sunucuda Gemini anahtarı yok",
                                fontSize = 13.sp, color = Renk.Soluk,
                            )
                        }
                        baglanti.hata != null -> Text(baglanti.hata!!, color = Renk.Kirmizi, fontSize = 14.sp)
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = { vm.baglantiyiDene() }) { Text("Bağlantıyı dene") }
                        TextButton(onClick = { vm.baglantiyiKaldir() }) { Text("Bağlantıyı kaldır") }
                    }
                } else {
                    Text("Henüz bağlı değil.", fontWeight = FontWeight.Bold)
                    baglanti.hata?.let { Text(it, color = Renk.Kirmizi, fontSize = 14.sp) }
                }
            }
            if (ayar.hazir) Kart(Modifier.fillMaxWidth()) {
                BolumBasligi("Sunucu")
                baglanti.veri?.let { d ->
                    Text("Sürüm: ${d.surum.ifBlank { "?" }}", fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                    if (d.aciklama.isNotBlank()) Text(d.aciklama, fontSize = 12.sp, color = Renk.Soluk)
                }
                Text(
                    "Yeni geliştirmeleri bilgisayara gerek kalmadan sunucuya kurar: önce veritabanını yedekler, " +
                        "sonra GitHub'daki son kodu alır ve botu yeniden başlatır (1-3 dk). Sonuç Telegram'a da gelir.",
                    fontSize = 13.sp, color = Renk.Soluk,
                )
                if (guncelleniyor) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                    Text("Sunucu güncelleniyor…", fontSize = 14.sp)
                } else Button(onClick = { guncelleSor = true }) { Text("Sunucuyu güncelle") }
            }
            Kart(Modifier.fillMaxWidth()) {
                BolumBasligi(if (ayar.hazir) "Yeni bağlantı kodu" else "Bağlantı kodu")
                Text(
                    "Telegram'da botuna /uygulama yaz. Gelen \"FOODY1.\" ile başlayan kodu uzun basıp kopyala, buraya yapıştır. " +
                        "Kod telefonda şifreli saklanır; yapıştırdıktan sonra Telegram'daki mesajı silebilirsin.",
                    fontSize = 13.sp, color = Renk.Soluk,
                )
                OutlinedTextField(kod, { kod = it }, Modifier.fillMaxWidth(), placeholder = { Text("FOODY1.…") }, maxLines = 4)
                Button(onClick = { vm.baglantiKoduKaydet(kod); kod = "" }, enabled = kod.isNotBlank()) { Text("Kaydet ve bağlan") }
            }
            Text("Foody ${BuildConfig.VERSION_NAME}", fontSize = 12.sp, color = Renk.Soluk)
        }
    }
}
