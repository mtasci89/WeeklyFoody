package com.foody.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.MenuBook
import androidx.compose.material.icons.rounded.Restaurant
import androidx.compose.material.icons.rounded.Rule
import androidx.compose.material.icons.rounded.ShoppingCart
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Türkçe büyük/küçük harf (i → İ). */
val TR: java.util.Locale = java.util.Locale.forLanguageTag("tr-TR")

object Renk {
    val Arka = Color(0xFFF6F4EF)
    val Kart = Color.White
    val Murekkep = Color(0xFF1C1917)
    val Soluk = Color(0xFF57534E)
    val Cizgi = Color(0xFFE7E5E4)
    val Yesil = Color(0xFF166534)
    val AcikYesil = Color(0xFFDCFCE7)
    val Turuncu = Color(0xFFC2410C)
    val AcikTuruncu = Color(0xFFFFEDD5)
    val Kirmizi = Color(0xFFB91C1C)
    val Sari = Color(0xFFFEF3C7)
}

@Composable
fun FoodyTema(icerik: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(
            primary = Renk.Yesil, onPrimary = Color.White, background = Renk.Arka, surface = Renk.Kart,
            onSurface = Renk.Murekkep, onBackground = Renk.Murekkep, secondaryContainer = Renk.AcikYesil,
        ),
        content = icerik,
    )
}

/** "2026-10-19" → "19 Eki" */
fun kisaTarih(iso: String): String = runCatching {
    val t = java.time.LocalDate.parse(iso)
    val aylar = listOf("Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara")
    "${t.dayOfMonth} ${aylar[t.monthValue - 1]}"
}.getOrDefault(iso)

/** 1150 → "1.150" */
fun binlik(sayi: Int): String = "%,d".format(TR, sayi)

fun kcalMetni(kcal: Int?, tahmini: Boolean?): String =
    if (kcal == null) "kalori ?" else (if (tahmini != false) "~" else "") + "${binlik(kcal)} kcal"

@Composable
fun Kart(
    modifier: Modifier = Modifier,
    renk: Color = Renk.Kart,
    tikla: (() -> Unit)? = null,
    icerik: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier
            .clip(RoundedCornerShape(20.dp))
            .background(renk)
            .then(if (tikla != null) Modifier.clickable(role = Role.Button, onClick = tikla) else Modifier)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        content = icerik,
    )
}

@Composable
fun BolumBasligi(metin: String, modifier: Modifier = Modifier) {
    Text(
        metin.uppercase(TR), modifier, fontSize = 13.sp, fontWeight = FontWeight.Bold,
        letterSpacing = 0.8.sp, color = Renk.Soluk,
    )
}

@Composable
fun Etiket(metin: String, arka: Color = Renk.AcikYesil, yazi: Color = Renk.Yesil) {
    Text(
        metin, Modifier.clip(RoundedCornerShape(6.dp)).background(arka).padding(horizontal = 7.dp, vertical = 2.dp),
        fontSize = 11.sp, fontWeight = FontWeight.Bold, color = yazi,
    )
}

/** Ekran başlığı: geri düğmesi, başlık, isteğe bağlı alt yazı ve sağ düğmeler. */
@Composable
fun Baslik(baslik: String, altYazi: String? = null, geri: (() -> Unit)? = null, sag: @Composable RowScope.() -> Unit = {}) {
    Row(
        Modifier.fillMaxWidth().padding(start = if (geri != null) 4.dp else 16.dp, end = 8.dp, top = 10.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (geri != null) IconButton(onClick = geri) {
            Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = "Geri", tint = Renk.Murekkep)
        }
        Column(Modifier.weight(1f)) {
            Text(baslik, fontSize = 22.sp, fontWeight = FontWeight.ExtraBold, color = Renk.Murekkep)
            if (altYazi != null) Text(altYazi, fontSize = 12.sp, color = Renk.Soluk)
        }
        sag()
    }
}

/** Yükleniyor / hata / boş durumları tek yerde. */
@Composable
fun DurumKarti(yukleniyor: Boolean, hata: String?, yenile: () -> Unit, modifier: Modifier = Modifier) {
    when {
        yukleniyor -> Row(modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
            Text("Yükleniyor…", color = Renk.Soluk)
        }
        hata != null -> Kart(modifier.padding(horizontal = 16.dp).fillMaxWidth(), renk = Color(0xFFFEE2E2)) {
            Text(hata, color = Renk.Kirmizi, fontSize = 14.sp)
            TextButton(onClick = yenile) { Text("Tekrar dene") }
        }
    }
}

/** Alt menü: Asistan (ana ekran) · Menü · Alışveriş · Tarifler · Kurallar */
@Composable
fun AltMenu(secili: String, sec: (String) -> Unit) {
    Row(
        Modifier.fillMaxWidth().background(Color.White).height(72.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MenuOgesi(Icons.Rounded.AutoAwesome, "Asistan", secili == "asistan", Modifier.weight(1f)) { sec("asistan") }
        MenuOgesi(Icons.Rounded.Restaurant, "Menü", secili == "menu", Modifier.weight(1f)) { sec("menu") }
        MenuOgesi(Icons.Rounded.ShoppingCart, "Alışveriş", secili == "alisveris", Modifier.weight(1f)) { sec("alisveris") }
        MenuOgesi(Icons.Rounded.MenuBook, "Tarifler", secili == "tarifler", Modifier.weight(1f)) { sec("tarifler") }
        MenuOgesi(Icons.Rounded.Rule, "Kurallar", secili == "kurallar", Modifier.weight(1f)) { sec("kurallar") }
    }
}

@Composable
private fun MenuOgesi(ikon: ImageVector, ad: String, secili: Boolean, modifier: Modifier, tikla: () -> Unit) {
    val renk = if (secili) Renk.Yesil else Renk.Soluk
    Column(
        modifier.clickable(role = Role.Tab, onClick = tikla).padding(vertical = 10.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        Icon(ikon, contentDescription = null, tint = renk)
        Text(ad, fontSize = 12.sp, fontWeight = if (secili) FontWeight.Bold else FontWeight.SemiBold, color = renk)
    }
}
