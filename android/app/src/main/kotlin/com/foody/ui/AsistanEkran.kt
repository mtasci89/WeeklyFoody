package com.foody.ui

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.material.icons.rounded.AddPhotoAlternate
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.PhotoCamera
import androidx.compose.material.icons.rounded.PhotoLibrary
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.Dp
import androidx.core.content.FileProvider
import com.foody.data.Gorsel
import java.io.File
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Send
import androidx.compose.material3.AssistChip
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

private val ONERILER = listOf(
    "Gelecek hafta için yeni bir menü hazırla",
    "Menüyü onayla ve gönder",
    "Salı'yı daha hafif yap",
    "İnternette yeni bir mercimek yemeği bul",
    "Bu hafta kaç kalori yiyoruz?",
)

@Composable
fun AsistanEkran(vm: AnaViewModel, menuyeGit: () -> Unit) {
    val sohbet by vm.sohbet.collectAsStateWithLifecycle()
    val calisiyor by vm.asistanCalisiyor.collectAsStateWithLifecycle()
    val taslak by vm.taslak.collectAsStateWithLifecycle()
    val ayar by vm.ayarlar.collectAsStateWithLifecycle()
    val ekler by vm.ekler.collectAsStateWithLifecycle()
    val baslangic by vm.asistanBaslangic.collectAsStateWithLifecycle()
    var simdi by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(calisiyor) { while (calisiyor) { simdi = System.currentTimeMillis(); kotlinx.coroutines.delay(1000) } }
    var girdi by rememberSaveable { mutableStateOf("") }
    var ekMenusu by remember { mutableStateOf(false) }
    val liste = rememberLazyListState()
    val baglam = LocalContext.current
    // İzin istemeyen sistem fotoğraf seçicisi ve telefonun kendi kamera uygulaması:
    // uygulamaya kamera/depolama izni eklenmez (banka uyumu, PROJE.md).
    val galeri = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(Gorsel.EN_COK)) { uriler ->
        uriler.forEach(vm::gorselEkle)
    }
    var kameraUri by rememberSaveable { mutableStateOf<Uri?>(null) }
    val kamera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { cekildi ->
        if (cekildi) kameraUri?.let(vm::gorselEkle)
    }

    LaunchedEffect(taslak) { if (taslak.isNotEmpty()) { girdi = taslak; vm.taslakKullanildi() } }
    LaunchedEffect(sohbet.size, calisiyor) { if (sohbet.isNotEmpty()) liste.animateScrollToItem(sohbet.size) }

    fun gonder(metin: String) { vm.asistanaSor(metin); girdi = "" }

    Column(Modifier.fillMaxSize().imePadding()) {
        Baslik("Asistan", "Menü kurar, değiştirir, tarif bulur")
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = liste, verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item {
                Balon(
                    false,
                    if (ayar.hazir) "Merhaba! Haftalık menüyü kurabilir, bir öğünü değiştirebilir, internetten yeni tarif bulup listene ekleyebilirim. Kalıcı bir şey söylersen (\"bundan sonra balık olmasın\") kurallara eklerim."
                    else "Merhaba! Konuşabilmemiz için önce Ayarlar'dan bağlantı kodunu girmen gerekiyor.",
                )
            }
            itemsIndexed(sohbet) { _, m ->
                Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (m.gorseller.isNotEmpty()) Row(
                        Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.End),
                    ) { m.gorseller.forEach { Onizleme(it, 72.dp) } }
                    if (m.metin.isNotBlank()) Balon(m.kullanici, m.metin, kenarsiz = true, hata = m.hata)
                    if (m.kaloriOzeti.isNotBlank()) Kart(Modifier.fillMaxWidth(), renk = Renk.AcikTuruncu) {
                        Text(m.kaloriOzeti, fontSize = 13.sp, lineHeight = 19.sp)
                    }
                    if (m.planDegisti) TextButton(onClick = menuyeGit) { Text("Menüyü gör") }
                }
            }
            if (calisiyor) item {
                Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    Text(
                        "Asistan çalışıyor… ${gecenSure(baslangic, simdi)}\nBaşka uygulamaya geçebilirsin; döndüğünde cevap burada olur.",
                        color = Renk.Soluk, fontSize = 13.sp, lineHeight = 18.sp,
                    )
                }
            }
        }
        if (sohbet.isEmpty() && ayar.hazir) Row(
            Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            ONERILER.forEach { o -> AssistChip(onClick = { gonder(o) }, label = { Text(o, fontSize = 12.sp) }) }
        }
        if (ekler.isNotEmpty()) Row(
            Modifier.horizontalScroll(rememberScrollState()).padding(start = 16.dp, end = 16.dp, top = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            ekler.forEach { ek ->
                Box {
                    Onizleme(ek.onizleme, 64.dp)
                    IconButton(
                        onClick = { vm.ekiCikar(ek.id) }, Modifier.align(Alignment.TopEnd).size(24.dp),
                        colors = IconButtonDefaults.iconButtonColors(containerColor = Color(0xCC000000), contentColor = Color.White),
                    ) { Icon(Icons.Rounded.Close, contentDescription = "Fotoğrafı çıkar", Modifier.size(14.dp)) }
                }
            }
        }
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Box {
                IconButton(onClick = { ekMenusu = true }, enabled = ayar.hazir && ekler.size < Gorsel.EN_COK) {
                    Icon(Icons.Rounded.AddPhotoAlternate, contentDescription = "Fotoğraf ekle", tint = Renk.Yesil)
                }
                DropdownMenu(expanded = ekMenusu, onDismissRequest = { ekMenusu = false }) {
                    DropdownMenuItem(
                        text = { Text("Galeriden seç") },
                        leadingIcon = { Icon(Icons.Rounded.PhotoLibrary, contentDescription = null) },
                        onClick = {
                            ekMenusu = false
                            galeri.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                        },
                    )
                    DropdownMenuItem(
                        text = { Text("Fotoğraf çek") },
                        leadingIcon = { Icon(Icons.Rounded.PhotoCamera, contentDescription = null) },
                        onClick = {
                            ekMenusu = false
                            val uri = kameraDosyasi(baglam)
                            kameraUri = uri
                            kamera.launch(uri)
                        },
                    )
                }
            }
            OutlinedTextField(
                girdi, { girdi = it }, Modifier.weight(1f),
                placeholder = { Text(if (ekler.isEmpty()) "Bir şey iste ya da sor…" else "Fotoğrafla ne yapayım? (örn. bunları ekle)") },
                shape = RoundedCornerShape(24.dp), maxLines = 4, enabled = ayar.hazir,
            )
            IconButton(
                onClick = { gonder(girdi) }, enabled = (girdi.isNotBlank() || ekler.isNotEmpty()) && !calisiyor && ayar.hazir,
                colors = IconButtonDefaults.iconButtonColors(containerColor = Renk.Yesil, contentColor = Color.White),
            ) { Icon(Icons.AutoMirrored.Rounded.Send, contentDescription = "Gönder") }
        }
    }
}

/** "1 dk 05 sn" */
fun gecenSure(baslangic: Long, simdi: Long): String {
    val sn = ((simdi - baslangic) / 1000).coerceAtLeast(0)
    return if (sn < 60) "$sn sn" else "${sn / 60} dk ${"%02d".format(sn % 60)} sn"
}

/** Kameranın fotoğrafı yazacağı geçici dosya (uygulamanın önbelleğinde, FileProvider ile paylaşılır). */
private fun kameraDosyasi(baglam: Context): Uri {
    val klasor = File(baglam.cacheDir, "kamera").apply { mkdirs() }
    klasor.listFiles()?.forEach { it.delete() }
    val dosya = File.createTempFile("foto", ".jpg", klasor)
    return FileProvider.getUriForFile(baglam, "${baglam.packageName}.dosyalar", dosya)
}

@Composable
private fun Onizleme(bitmap: android.graphics.Bitmap, boyut: Dp) {
    Image(
        bitmap.asImageBitmap(), contentDescription = "Eklenen fotoğraf",
        Modifier.size(boyut).clip(RoundedCornerShape(12.dp)), contentScale = ContentScale.Crop,
    )
}

@Composable
private fun Balon(kullanici: Boolean, metin: String, kenarsiz: Boolean = false, hata: Boolean = false) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = if (kenarsiz) 0.dp else 16.dp),
        horizontalArrangement = if (kullanici) Arrangement.End else Arrangement.Start,
    ) {
        SelectionContainer {
            Text(
                metin,
                Modifier.widthIn(max = 320.dp)
                    .clip(RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomStart = if (kullanici) 18.dp else 6.dp, bottomEnd = if (kullanici) 6.dp else 18.dp))
                    .background(if (kullanici) Renk.Yesil else if (hata) Color(0xFFFEE2E2) else Color.White)
                    .padding(horizontal = 14.dp, vertical = 10.dp),
                color = if (kullanici) Color.White else if (hata) Renk.Kirmizi else Renk.Murekkep,
                fontSize = 14.sp, lineHeight = 20.sp,
            )
        }
    }
}
