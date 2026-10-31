package com.foody.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.RadioButtonUnchecked
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.foody.data.Degisiklik
import com.foody.data.Gun
import com.foody.data.MenuCevap
import com.foody.data.Ogun
import com.foody.data.Plan

const val HAFTA = "HAFTA"

/** "Pazartesi" → "Pzt" */
fun kisaGun(gun: String): String = when (gun.lowercase(TR)) {
    "pazartesi" -> "Pzt"
    "salı" -> "Sal"
    "çarşamba" -> "Çar"
    "perşembe" -> "Per"
    "cuma" -> "Cum"
    "cumartesi" -> "Cmt"
    "pazar" -> "Paz"
    else -> gun.take(3)
}

fun degisimAnahtari(tarih: String, slot: String) = "$tarih|$slot"

/** Değişen öğünlerin anahtarları (eklenen ya da yerine konan; çıkarılanlar tabloda yok). */
fun degisenAnahtarlar(degisiklikler: List<Degisiklik>): Set<String> =
    degisiklikler.filter { it.yeni != null }.map { degisimAnahtari(it.tarih, it.slot) }.toSet()

/** İki plan arasındaki fark (elle düzenlemeden sonra vurgulamak için). */
fun planFarki(eski: Plan?, yeni: Plan): List<Degisiklik> {
    fun harita(p: Plan?): Map<Pair<String, String>, String> {
        if (p == null) return emptyMap()
        return p.gunler.flatMap { g -> g.ogunler.map { (g.tarih to it.slot) to it.tarif } }.toMap() +
            p.mezeler.associate { (HAFTA to it.slot) to it.tarif }
    }
    if (eski == null) return emptyList()
    val once = harita(eski)
    val sonra = harita(yeni)
    return (once.keys + sonra.keys).distinct().sortedWith(compareBy({ it.first }, { it.second }))
        .filter { once[it] != sonra[it] }
        .map { Degisiklik(it.first, it.second, once[it], sonra[it]) }
}

/** "Salı · Ana yemek: Izgara Balık → Izgara Köfte", "Mezeler: + Atom", "Mezeler: − Çoban Salata" */
fun degisiklikMetni(d: Degisiklik, plan: Plan?): String {
    val yer = if (d.tarih == HAFTA) "Mezeler" else {
        val gun = plan?.gunler?.firstOrNull { it.tarih == d.tarih }
        val rol = gun?.ogunler?.firstOrNull { it.slot == d.slot }?.rol
        listOfNotNull(gun?.gun ?: kisaTarih(d.tarih), rol).joinToString(" · ")
    }
    val ne = when {
        d.eski == null -> "+ ${d.yeni}"
        d.yeni == null -> "− ${d.eski}"
        else -> "${d.eski} → ${d.yeni}"
    }
    return "$yer: $ne"
}

/**
 * Haftanın tek bakışta görünen tablosu: her gün bir satır, sonra haftalık meze listesi.
 * `tikla` verilirse yemekler dokunulabilir; `degisen` anahtarlarındaki yemekler vurgulanır.
 */
@Composable
fun MenuTablosu(
    menu: MenuCevap,
    modifier: Modifier = Modifier,
    degisen: Set<String> = emptySet(),
    kompakt: Boolean = false,
    tikla: ((Gun?, Ogun) -> Unit)? = null,
    gunEkle: ((Gun) -> Unit)? = null,
    mezeEkle: (() -> Unit)? = null,
    /** Çoklu seçim açıkken seçili yemeklerin anahtarları; null ise seçim kapalı. */
    secili: Set<String>? = null,
    /** Uzun basınca (çoklu seçimi başlatmak için). */
    uzunBas: ((Gun?, Ogun) -> Unit)? = null,
) {
    val plan = menu.plan ?: return
    Column(modifier, verticalArrangement = Arrangement.spacedBy(0.dp)) {
        plan.gunler.forEachIndexed { i, gun ->
            if (i > 0) HorizontalDivider(color = Renk.Cizgi)
            Row(
                Modifier.fillMaxWidth().heightIn(min = if (kompakt) 36.dp else 48.dp).padding(vertical = if (kompakt) 4.dp else 5.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.width(if (kompakt) 40.dp else 50.dp)) {
                    Text(kisaGun(gun.gun), fontWeight = FontWeight.ExtraBold, fontSize = if (kompakt) 13.sp else 15.sp, color = Renk.Murekkep)
                    if (!kompakt) Text(kisaTarih(gun.tarih), fontSize = 11.sp, color = Renk.Soluk)
                }
                if (kompakt) {
                    KompaktSatir(gun.ogunler.map { it to (degisimAnahtari(gun.tarih, it.slot) in degisen) }, Modifier.weight(1f))
                } else Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    if (gun.ogunler.isEmpty()) Text("Boş (dışarıda)", fontSize = 14.sp, color = Renk.Soluk)
                    gun.ogunler.forEachIndexed { j, ogun ->
                        YemekSatiri(
                            ogun, ana = j == 0, kompakt = kompakt,
                            vurgulu = degisimAnahtari(gun.tarih, ogun.slot) in degisen,
                            kalori = if (menu.kaloriGoster && !kompakt) ogun.kcal else null,
                            tikla = tikla?.let { t -> { t(gun, ogun) } },
                            secildi = secili?.let { degisimAnahtari(gun.tarih, ogun.slot) in it },
                            uzunBas = uzunBas?.let { u -> { u(gun, ogun) } },
                        )
                    }
                }
                if (gunEkle != null && secili == null) IconButton(onClick = { gunEkle(gun) }) {
                    Icon(Icons.Rounded.Add, contentDescription = "${gun.gun} günü ekle", tint = Renk.Yesil)
                }
            }
        }
        if (plan.mezeler.isNotEmpty() || mezeEkle != null) {
            HorizontalDivider(color = Renk.Cizgi, thickness = 2.dp)
            Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "Haftanın mezeleri", Modifier.weight(1f), fontWeight = FontWeight.ExtraBold,
                    fontSize = if (kompakt) 13.sp else 15.sp, color = Renk.Murekkep,
                )
                if (mezeEkle != null) IconButton(onClick = mezeEkle) {
                    Icon(Icons.Rounded.Add, contentDescription = "Meze ekle", tint = Renk.Yesil)
                }
            }
            if (plan.mezeler.isEmpty()) Text("Meze yok.", fontSize = 14.sp, color = Renk.Soluk)
            if (kompakt) {
                KompaktSatir(plan.mezeler.map { it to (degisimAnahtari(HAFTA, it.slot) in degisen) }, Modifier.fillMaxWidth())
            } else plan.mezeler.forEach { meze ->
                YemekSatiri(
                    meze, ana = false, kompakt = kompakt,
                    vurgulu = degisimAnahtari(HAFTA, meze.slot) in degisen,
                    kalori = null,
                    tikla = tikla?.let { t -> { t(null, meze) } },
                    secildi = secili?.let { degisimAnahtari(HAFTA, meze.slot) in it },
                    uzunBas = uzunBas?.let { u -> { u(null, meze) } },
                )
            }
        }
    }
}

/** Sohbet kartında bir günün yemekleri tek satırda: "Fırında Tavuk · Makarna"; değişenler vurgulu. */
@Composable
private fun KompaktSatir(yemekler: List<Pair<Ogun, Boolean>>, modifier: Modifier) {
    if (yemekler.isEmpty()) {
        Text("Boş (dışarıda)", modifier, fontSize = 13.sp, color = Renk.Soluk)
        return
    }
    val metin = buildAnnotatedString {
        yemekler.forEachIndexed { i, (ogun, vurgulu) ->
            if (i > 0) append(" · ")
            val stil = when {
                vurgulu -> SpanStyle(background = Renk.AcikYesil, fontWeight = FontWeight.Bold, color = Renk.Yesil)
                i == 0 -> SpanStyle(fontWeight = FontWeight.SemiBold, color = Renk.Murekkep)
                else -> SpanStyle(color = Renk.Soluk)
            }
            withStyle(stil) { append(ogun.tarif) }
            if (ogun.yeni) withStyle(SpanStyle(color = Renk.Turuncu, fontWeight = FontWeight.Bold, fontSize = 11.sp)) { append(" yeni") }
        }
    }
    Text(metin, modifier, fontSize = 14.sp, lineHeight = 19.sp)
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun YemekSatiri(
    ogun: Ogun, ana: Boolean, kompakt: Boolean, vurgulu: Boolean, kalori: Int?, tikla: (() -> Unit)?,
    /** null: seçim kapalı; true/false: çoklu seçimde seçili mi. */
    secildi: Boolean? = null,
    uzunBas: (() -> Unit)? = null,
) {
    val zemin = when {
        secildi == true -> Renk.AcikTuruncu
        vurgulu -> Renk.AcikYesil
        else -> Color.Transparent
    }
    Row(
        Modifier.fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(zemin)
            .then(
                when {
                    tikla != null && uzunBas != null -> Modifier.combinedClickable(onClick = tikla, onLongClick = uzunBas)
                    tikla != null -> Modifier.clickable(onClick = tikla)
                    else -> Modifier
                }
            )
            .padding(horizontal = if (vurgulu || secildi == true) 6.dp else 0.dp, vertical = if (kompakt) 1.dp else 2.dp)
            .testTag("yemek_${ogun.slot}"),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (secildi != null) Icon(
            if (secildi) Icons.Rounded.CheckCircle else Icons.Rounded.RadioButtonUnchecked,
            contentDescription = if (secildi) "Seçili" else "Seçili değil",
            tint = if (secildi) Renk.Turuncu else Renk.Soluk,
            modifier = Modifier.size(20.dp),
        )
        Text(
            ogun.tarif, Modifier.weight(1f, fill = false),
            fontSize = if (kompakt) 13.sp else if (ana) 15.sp else 14.sp,
            fontWeight = if (ana || vurgulu) FontWeight.SemiBold else FontWeight.Normal,
            color = if (ana || vurgulu) Renk.Murekkep else Renk.Soluk,
            maxLines = 1, overflow = TextOverflow.Ellipsis,
        )
        if (ogun.yeni) Text(
            "yeni", fontSize = 10.sp, fontWeight = FontWeight.Bold, color = Renk.Turuncu,
            modifier = Modifier.clip(RoundedCornerShape(5.dp)).background(Renk.AcikTuruncu).padding(horizontal = 5.dp),
        )
        if (kalori != null) Text(kcalMetni(kalori, ogun.tahmini), fontSize = 11.sp, color = Renk.Soluk)
    }
}

/** Asistanın yaptığı değişikliklerin listesi; çıkarılanlar üstü çizili. */
@Composable
fun DegisiklikListesi(degisiklikler: List<Degisiklik>, plan: Plan?) {
    if (degisiklikler.isEmpty()) return
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        BolumBasligi("Değişenler")
        degisiklikler.forEach { d ->
            Text(
                degisiklikMetni(d, plan), fontSize = 14.sp, lineHeight = 19.sp,
                color = if (d.yeni == null) Renk.Soluk else Renk.Murekkep,
                textDecoration = if (d.yeni == null) TextDecoration.LineThrough else null,
                fontWeight = if (d.yeni != null) FontWeight.SemiBold else FontWeight.Normal,
            )
        }
    }
}

/** Sohbetteki menü kartı: değişenler + haftanın tablosu + menüye git / onayla. */
@Composable
fun MenuKarti(
    menu: MenuCevap,
    degisiklikler: List<Degisiklik>,
    menuyuAc: () -> Unit,
    onayla: (() -> Unit)?,
    modifier: Modifier = Modifier,
) {
    val plan = menu.plan ?: return
    Kart(modifier.fillMaxWidth().testTag("menu_karti")) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("${kisaTarih(plan.haftaBaslangic)} – ${kisaTarih(plan.haftaBitis)} menüsü", fontWeight = FontWeight.ExtraBold, fontSize = 15.sp)
                Text(plan.durumMetni, fontSize = 12.sp, color = Renk.Soluk)
            }
        }
        DegisiklikListesi(degisiklikler, plan)
        MenuTablosu(menu, degisen = degisenAnahtarlar(degisiklikler), kompakt = true)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            androidx.compose.material3.OutlinedButton(onClick = menuyuAc) { Text(if (plan.onaylanabilir) "Taslağı aç" else "Menüyü aç") }
            if (onayla != null && plan.onaylanabilir) androidx.compose.material3.Button(onClick = onayla) { Text("Onayla") }
        }
    }
}
