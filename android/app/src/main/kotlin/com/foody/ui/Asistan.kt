package com.foody.ui

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
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
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.PhotoCamera
import androidx.compose.material.icons.rounded.PhotoLibrary
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.InputChip
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.foody.data.Gorsel
import java.io.File

/** Menünün altındaki asistan: hiç konuşulmadıysa öneriler, sonra son cevap ya da tüm sohbet. */
private val ONERILER = listOf(
    "Bu haftayı daha yenilikçi yap" to HAFTAYI_YENILE_ISTEK,
    "Salı'yı daha hafif yap" to "Salı'yı daha hafif yap",
    "Menüyü onayla ve gönder" to "Menüyü onayla ve gönder",
    "Bu hafta kaç kalori yiyoruz?" to "Bu hafta kaç kalori yiyoruz?",
)

@Composable
fun AsistanPaneli(vm: AnaViewModel, acik: Boolean, acKapat: () -> Unit, modifier: Modifier = Modifier) {
    val sohbet by vm.sohbet.collectAsStateWithLifecycle()
    val calisiyor by vm.asistanCalisiyor.collectAsStateWithLifecycle()
    val baslangic by vm.asistanBaslangic.collectAsStateWithLifecycle()
    val secili by vm.secili.collectAsStateWithLifecycle()
    var simdi by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(calisiyor) { while (calisiyor) { simdi = System.currentTimeMillis(); kotlinx.coroutines.delay(1000) } }
    val calisiyorMetni = "Asistan çalışıyor… ${gecenSure(baslangic, simdi)}"

    Column(modifier.fillMaxWidth().background(Renk.AcikYesil)) {
        HorizontalDivider(color = Renk.Cizgi)
        Row(
            Modifier.fillMaxWidth().clickable(enabled = sohbet.isNotEmpty(), onClick = acKapat)
                .padding(start = 16.dp, end = 8.dp, top = 6.dp, bottom = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Rounded.AutoAwesome, contentDescription = null, tint = Renk.Yesil, modifier = Modifier.size(16.dp))
            Text(" Asistan", fontWeight = FontWeight.Bold, fontSize = 13.sp, color = Renk.Yesil, modifier = Modifier.weight(1f))
            if (sohbet.isNotEmpty()) Row(verticalAlignment = Alignment.CenterVertically) {
                Text(if (acik) "Küçült" else "Tüm sohbet", fontSize = 12.sp, color = Renk.Yesil)
                Icon(if (acik) Icons.Rounded.ExpandMore else Icons.Rounded.ExpandLess, contentDescription = null, tint = Renk.Yesil)
            }
        }
        when {
            acik -> SohbetListesi(vm, if (calisiyor) calisiyorMetni else null, Modifier.weight(1f))
            calisiyor -> Calisiyor(calisiyorMetni)
            sohbet.isEmpty() && secili.isEmpty() -> Row(
                Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp).padding(bottom = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) { ONERILER.forEach { (ad, istek) -> AssistChip(onClick = { vm.asistanaSor(istek) }, label = { Text(ad, fontSize = 12.sp) }) } }
            sohbet.isNotEmpty() -> {
                val son = sohbet.last()
                Text(
                    when {
                        !son.kullanici -> son.metin
                        son.metin.isNotBlank() -> "Sen: ${son.metin}"
                        else -> "Sen: 📷 ${son.gorseller.size} fotoğraf"
                    },
                    Modifier.fillMaxWidth().clickable(onClick = acKapat).padding(horizontal = 16.dp).padding(bottom = 6.dp)
                        .testTag("son_cevap"),
                    color = if (son.hata) Renk.Kirmizi else Renk.Murekkep,
                    fontSize = 14.sp, lineHeight = 19.sp, maxLines = 4, overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun Calisiyor(metin: String) {
    Row(
        Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
        Text(
            "$metin\nBaşka uygulamaya geçebilirsin; cevap burada olur, menü kendiliğinden güncellenir.",
            color = Renk.Soluk, fontSize = 12.sp, lineHeight = 16.sp,
        )
    }
}

@Composable
private fun SohbetListesi(vm: AnaViewModel, calisiyor: String?, modifier: Modifier) {
    val sohbet by vm.sohbet.collectAsStateWithLifecycle()
    val liste = rememberLazyListState()
    LaunchedEffect(sohbet.size, calisiyor != null) { if (sohbet.isNotEmpty()) liste.animateScrollToItem(sohbet.size) }
    LazyColumn(
        modifier.fillMaxWidth().testTag("sohbet_listesi"), state = liste,
        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(sohbet) { m ->
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                if (m.gorseller.isNotEmpty()) Row(
                    Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.End),
                ) { m.gorseller.forEach { Onizleme(it, 72.dp) } }
                if (m.metin.isNotBlank()) Balon(m.kullanici, m.metin, hata = m.hata)
                if (m.kaloriOzeti.isNotBlank()) Kart(Modifier.fillMaxWidth(), renk = Renk.AcikTuruncu) {
                    Text(m.kaloriOzeti, fontSize = 13.sp, lineHeight = 19.sp)
                }
            }
        }
        if (calisiyor != null) item { Calisiyor(calisiyor) }
    }
}

/** Seçili yemekler ve onlarla yapılabilecekler; yalnızca seçim varken görünür. */
@Composable
fun SecimCubugu(vm: AnaViewModel, listedenSec: (SeciliOgun) -> Unit) {
    val secili by vm.secili.collectAsStateWithLifecycle()
    val calisiyor by vm.asistanCalisiyor.collectAsStateWithLifecycle()
    if (secili.isEmpty()) return
    Column(Modifier.fillMaxWidth().background(Color.White).padding(top = 6.dp)) {
        Row(
            Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            secili.forEach { o ->
                InputChip(
                    selected = true, onClick = { vm.ogunSec(o) },
                    label = { Text("${o.gun} · ${o.tarif}", fontSize = 12.sp) },
                    trailingIcon = { Icon(Icons.Rounded.Close, contentDescription = "${o.tarif} seçimini kaldır", Modifier.size(16.dp)) },
                )
            }
        }
        Row(
            Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically,
        ) {
            Button(onClick = { vm.asistanaSor(YENILIKCI_ISTEK) }, enabled = !calisiyor) {
                Icon(Icons.Rounded.AutoAwesome, contentDescription = null, Modifier.size(16.dp))
                Text(" Daha yenilikçi bir şey koy", fontSize = 13.sp)
            }
            if (secili.size == 1) OutlinedButton(onClick = { listedenSec(secili.first()) }) { Text("Listeden seç", fontSize = 13.sp) }
            TextButton(onClick = { vm.secimiTemizle() }) { Text("Temizle", fontSize = 13.sp) }
        }
    }
}

/** Yazı alanı, fotoğraf ekleme ve gönder. */
@Composable
fun AsistanCubugu(vm: AnaViewModel) {
    val calisiyor by vm.asistanCalisiyor.collectAsStateWithLifecycle()
    val ayar by vm.ayarlar.collectAsStateWithLifecycle()
    val ekler by vm.ekler.collectAsStateWithLifecycle()
    val secili by vm.secili.collectAsStateWithLifecycle()
    var girdi by rememberSaveable { mutableStateOf("") }
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
                girdi, { girdi = it }, Modifier.weight(1f),
                placeholder = {
                    Text(
                        when {
                            secili.isNotEmpty() -> "Seçtiklerinle ne yapayım?"
                            ekler.isNotEmpty() -> "Fotoğrafla ne yapayım? (örn. bunları ekle)"
                            else -> "Asistana yaz: değiştir, ekle, sor…"
                        },
                        fontSize = 14.sp,
                    )
                },
                shape = RoundedCornerShape(24.dp), maxLines = 4, enabled = ayar.hazir,
            )
            IconButton(
                onClick = { vm.asistanaSor(girdi); girdi = "" },
                enabled = (girdi.isNotBlank() || ekler.isNotEmpty() || secili.isNotEmpty()) && !calisiyor && ayar.hazir,
                colors = IconButtonDefaults.iconButtonColors(
                    containerColor = Renk.Yesil, contentColor = Color.White,
                    disabledContainerColor = Renk.Cizgi, disabledContentColor = Color.White,
                ),
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
private fun Balon(kullanici: Boolean, metin: String, hata: Boolean = false) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (kullanici) Arrangement.End else Arrangement.Start) {
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
