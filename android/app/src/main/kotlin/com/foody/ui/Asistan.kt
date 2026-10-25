package com.foody.ui

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Send
import androidx.compose.material.icons.rounded.AddPhotoAlternate
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.PhotoCamera
import androidx.compose.material.icons.rounded.PhotoLibrary
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.foody.data.Gorsel
import com.foody.data.Plan
import java.io.File

private val ONERILER = listOf(
    "Gelecek haftanın menüsünü hazırla",
    "Menüyü daha yenilikçi yap",
    "Salı'yı daha hafif yap",
    "Cumartesi kişi sayısını değiştir",
)

/**
 * Uygulamanın ana ekranı: tam ekran sohbet. Asistan planı değiştirince cevabın altında
 * haftanın tablosu ve değişenler kart olarak çıkar; menü metin olarak okunmak zorunda kalmaz.
 */
@Composable
fun AsistanEkran(vm: AnaViewModel, menuyuAc: (Plan) -> Unit, ayarlar: () -> Unit) {
    val sohbet by vm.sohbet.collectAsStateWithLifecycle()
    val calisiyor by vm.asistanCalisiyor.collectAsStateWithLifecycle()
    val baslangic by vm.asistanBaslangic.collectAsStateWithLifecycle()
    val ayar by vm.ayarlar.collectAsStateWithLifecycle()
    val menu by vm.menu.collectAsStateWithLifecycle()
    val taslak by vm.taslak.collectAsStateWithLifecycle()
    var girdi by rememberSaveable { mutableStateOf("") }
    var onaylanacak by remember { mutableStateOf<Plan?>(null) }
    var simdi by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(calisiyor) { while (calisiyor) { simdi = System.currentTimeMillis(); kotlinx.coroutines.delay(1000) } }
    LaunchedEffect(taslak) { if (taslak.isNotEmpty()) { girdi = taslak; vm.taslakKullanildi() } }
    val liste = rememberLazyListState()
    // Yeni cevabın BAŞINA kay: metin ve değişenler önce görünsün (kartın sonu değil).
    LaunchedEffect(sohbet.size, calisiyor) {
        if (sohbet.isNotEmpty()) liste.animateScrollToItem(if (calisiyor) sohbet.size else sohbet.size - 1)
    }
    val guncel = menu.veri?.plan

    Column(Modifier.fillMaxSize().imePadding()) {
        Baslik(
            "Asistan",
            guncel?.let { "Menü: ${kisaTarih(it.haftaBaslangic)} – ${kisaTarih(it.haftaBitis)} · ${it.durumMetni}" },
        ) {
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
        LazyColumn(
            Modifier.weight(1f).fillMaxWidth().testTag("sohbet_listesi"), state = liste,
            contentPadding = PaddingValues(horizontal = 14.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (sohbet.isEmpty()) {
                item {
                    Balon(
                        false,
                        "Merhaba! Menüyü buradan yönetiyoruz: \"gelecek haftayı hazırla\", \"Salı'daki köfte olmamış, " +
                            "daha yenilikçi bir şey koy\", \"meze listesine Atom ekle\" diyebilirsin. Değişen menüyü " +
                            "burada tablo olarak gösteririm.",
                    )
                }
                val m = menu.veri
                if (m?.plan != null) item {
                    MenuKarti(m, emptyList(), menuyuAc = { menuyuAc(m.plan!!) }, onayla = { onaylanacak = m.plan })
                }
            }
            items(sohbet) { mesaj ->
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (mesaj.gorseller.isNotEmpty()) Row(
                        Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.End),
                    ) { mesaj.gorseller.forEach { Onizleme(it, 80.dp) } }
                    if (mesaj.metin.isNotBlank()) Balon(mesaj.kullanici, mesaj.metin, hata = mesaj.hata)
                    val m = mesaj.menu
                    if (m?.plan != null) {
                        MenuKarti(m, mesaj.degisiklikler, menuyuAc = { menuyuAc(m.plan!!) }, onayla = { onaylanacak = m.plan })
                    }
                    // Menü kartı varken kalori dökümü Menü ekranında; sohbeti kalabalıklaştırmaz.
                    if (mesaj.kaloriOzeti.isNotBlank() && m?.plan == null) Kart(Modifier.fillMaxWidth(), renk = Renk.AcikTuruncu) {
                        Text(mesaj.kaloriOzeti, fontSize = 13.sp, lineHeight = 19.sp)
                    }
                }
            }
            if (calisiyor) item {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    Text(
                        "Asistan çalışıyor… ${gecenSure(baslangic, simdi)}\nBaşka uygulamaya geçebilirsin; cevap burada olur.",
                        color = Renk.Soluk, fontSize = 13.sp, lineHeight = 18.sp,
                    )
                }
            }
        }
        Row(
            Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) { ONERILER.forEach { o -> AssistChip(onClick = { girdi = o }, enabled = !calisiyor, label = { Text(o, fontSize = 13.sp) }) } }
        Text("Onaylı menüyü de değiştirebilirsin. Gün ve yemek adını yaz.", Modifier.padding(horizontal = 16.dp, vertical = 3.dp), color = Renk.Soluk, fontSize = 12.sp)
        YaziAlani(vm, girdi, { girdi = it }, gonder = { vm.asistanaSor(girdi); girdi = "" })
    }

    onaylanacak?.let { plan ->
        AlertDialog(
            onDismissRequest = { onaylanacak = null },
            title = { Text("Menü onaylansın mı?") },
            text = { Text("${kisaTarih(plan.haftaBaslangic)} – ${kisaTarih(plan.haftaBitis)} menüsü kesinleşir; tarifleri ve alışveriş listesi uygulamada hazır olur. Daha sonra düzenleyebilirsin; değişiklikler yeniden onay bekleyen taslağa dönüşür.") },
            confirmButton = { TextButton(onClick = { onaylanacak = null; vm.planiOnayla(plan) }) { Text("Onayla") } },
            dismissButton = { TextButton(onClick = { onaylanacak = null }) { Text("Vazgeç") } },
        )
    }
}

/** Yazı alanı, fotoğraf ekleme ve gönder. */
@Composable
private fun YaziAlani(vm: AnaViewModel, girdi: String, degis: (String) -> Unit, gonder: () -> Unit) {
    val calisiyor by vm.asistanCalisiyor.collectAsStateWithLifecycle()
    val ayar by vm.ayarlar.collectAsStateWithLifecycle()
    val ekler by vm.ekler.collectAsStateWithLifecycle()
    var ekMenusu by remember { mutableStateOf(false) }
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

    Column(Modifier.fillMaxWidth().background(Color.White)) {
        HorizontalDivider(color = Renk.Cizgi)
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
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(4.dp),
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
                girdi, degis, Modifier.weight(1f),
                placeholder = { Text(if (ekler.isEmpty()) "Asistana yaz…" else "Fotoğrafla ne yapayım? (örn. bunları ekle)", fontSize = 15.sp) },
                shape = RoundedCornerShape(24.dp), maxLines = 5, enabled = ayar.hazir,
            )
            IconButton(
                onClick = gonder,
                enabled = (girdi.isNotBlank() || ekler.isNotEmpty()) && !calisiyor && ayar.hazir,
                colors = IconButtonDefaults.iconButtonColors(
                    containerColor = Renk.Yesil, contentColor = Color.White,
                    disabledContainerColor = Renk.Cizgi, disabledContentColor = Color.White,
                ),
            ) { Icon(Icons.AutoMirrored.Rounded.Send, contentDescription = "Gönder") }
        }
    }
}

/** Asistanın metnindeki **kalın** kısımları kalın gösterir, baştaki "#" başlık işaretlerini atar. */
fun sadeMarkdown(metin: String): androidx.compose.ui.text.AnnotatedString = androidx.compose.ui.text.buildAnnotatedString {
    val temiz = metin.lines().joinToString("\n") { it.replace(Regex("^\\s*#{1,6}\\s+"), "") }
    var kalin = false
    temiz.split("**").forEachIndexed { i, parca ->
        if (i > 0) kalin = !kalin
        if (kalin) withStyle(androidx.compose.ui.text.SpanStyle(fontWeight = FontWeight.Bold)) { append(parca) } else append(parca)
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
private fun Balon(kullanici: Boolean, metin: String, hata: Boolean = false) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (kullanici) Arrangement.End else Arrangement.Start) {
        SelectionContainer {
            Text(
                if (kullanici) androidx.compose.ui.text.AnnotatedString(metin) else sadeMarkdown(metin),
                Modifier.widthIn(max = 330.dp)
                    .clip(RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp, bottomStart = if (kullanici) 20.dp else 6.dp, bottomEnd = if (kullanici) 6.dp else 20.dp))
                    .background(if (kullanici) Renk.Yesil else if (hata) Color(0xFFFEE2E2) else Color.White)
                    .padding(horizontal = 16.dp, vertical = 12.dp),
                color = if (kullanici) Color.White else if (hata) Renk.Kirmizi else Renk.Murekkep,
                fontSize = 16.sp, lineHeight = 23.sp,
            )
        }
    }
}
