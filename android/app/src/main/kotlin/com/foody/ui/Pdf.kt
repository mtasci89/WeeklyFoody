package com.foody.ui

import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import androidx.core.content.FileProvider
import com.foody.data.Alisveris
import com.foody.data.MenuCevap
import com.foody.data.TarifDetay
import java.io.File

/**
 * Menü, tarifler ve alışveriş listesi için telefonda PDF üretir ve paylaşır.
 * İzin gerekmez: dosya uygulamanın önbelleğine yazılır, FileProvider ile paylaşılır.
 */
sealed class PdfSatiri {
    data class Baslik(val metin: String) : PdfSatiri()
    data class AltYazi(val metin: String) : PdfSatiri()
    data class Bolum(val metin: String) : PdfSatiri()
    data class Ara(val metin: String) : PdfSatiri()
    data class Metin(val metin: String) : PdfSatiri()
    data class Madde(val metin: String) : PdfSatiri()
}

private fun durumYazisi(durumMetni: String, onaylanabilir: Boolean) =
    if (onaylanabilir) "Taslak (henüz onaylanmadı)" else durumMetni.ifBlank { "Onaylı" }

/** Haftanın menüsü: gün gün yemekler, sonra haftanın mezeleri. */
fun menuSatirlari(menu: MenuCevap): List<PdfSatiri> {
    val plan = menu.plan ?: return listOf(PdfSatiri.Baslik("Menü yok"))
    val satirlar = mutableListOf<PdfSatiri>(
        PdfSatiri.Baslik("Haftalık menü"),
        PdfSatiri.AltYazi("${kisaTarih(plan.haftaBaslangic)} – ${kisaTarih(plan.haftaBitis)} · ${durumYazisi(plan.durumMetni, plan.onaylanabilir)}"),
    )
    plan.gunler.forEach { gun ->
        satirlar += PdfSatiri.Bolum("${gun.gun} · ${kisaTarih(gun.tarih)}")
        if (gun.ogunler.isEmpty()) satirlar += PdfSatiri.Metin("Boş (dışarıda)")
        gun.ogunler.forEach { o ->
            val kcal = if (menu.kaloriGoster && o.kcal != null) " · ${kcalMetni(o.kcal, o.tahmini)}" else ""
            satirlar += PdfSatiri.Madde("${o.rol}: ${o.tarif}${if (o.yeni) " (yeni)" else ""}$kcal")
        }
        if (menu.kaloriGoster && gun.toplamKcal != null) satirlar += PdfSatiri.Metin("Kişi başı toplam ~${binlik(gun.toplamKcal)} kcal")
    }
    if (plan.mezeler.isNotEmpty()) {
        satirlar += PdfSatiri.Bolum("Haftanın mezeleri")
        plan.mezeler.forEach { satirlar += PdfSatiri.Madde(it.tarif + if (it.yeni) " (yeni)" else "") }
    }
    return satirlar
}

/** Menüdeki tariflerin hepsi: malzemeler ve hazırlanış. */
fun tarifSatirlari(baslik: String, altYazi: String, tarifler: List<TarifDetay>): List<PdfSatiri> {
    val satirlar = mutableListOf<PdfSatiri>(PdfSatiri.Baslik(baslik), PdfSatiri.AltYazi(altYazi))
    tarifler.forEach { t ->
        satirlar += PdfSatiri.Bolum(t.ad)
        val bilgi = listOfNotNull(
            t.gun.ifBlank { null }, "${t.kisi} kişilik", t.sureDk?.let { "$it dk" },
            t.kcal?.let { kcalMetni(it, t.tahmini) + " (kişi başı)" },
        )
        satirlar += PdfSatiri.Metin(bilgi.joinToString(" · "))
        satirlar += PdfSatiri.Ara("Malzemeler")
        t.malzemeler.forEach { m ->
            satirlar += PdfSatiri.Madde(listOf(m.miktar, m.ad).filter { it.isNotBlank() }.joinToString(" ") + if (m.not.isNotBlank()) " (${m.not})" else "")
        }
        val adim = adimlar(t.hazirlanis)
        if (adim.isNotEmpty()) {
            satirlar += PdfSatiri.Ara("Hazırlanışı")
            adim.forEachIndexed { i, a -> satirlar += PdfSatiri.Metin("${i + 1}. $a") }
        }
    }
    return satirlar
}

/** Alışveriş listesi: alınmamış kalemler kategori kategori. */
fun alisverisSatirlari(liste: Alisveris, isaretli: Set<String>): List<PdfSatiri> {
    val satirlar = mutableListOf<PdfSatiri>(
        PdfSatiri.Baslik("Alışveriş listesi"),
        PdfSatiri.AltYazi(liste.haftaBaslangic?.let { "${kisaTarih(it)} haftası" } ?: ""),
    )
    liste.gruplar.forEach { g ->
        val kalan = g.kalemler.filter { it.anahtar !in isaretli }
        if (kalan.isNotEmpty()) {
            satirlar += PdfSatiri.Bolum(g.kategori)
            kalan.forEach { satirlar += PdfSatiri.Madde("☐  ${it.metin}") }
        }
    }
    return satirlar
}

private const val GENISLIK = 595 // A4, nokta
private const val YUKSEKLIK = 842
private const val KENAR = 48f

/** Satırları A4 sayfalara dizer, uygulamanın önbelleğine yazar. Sayfa sayısını da döndürür. */
fun pdfYaz(baglam: Context, ad: String, satirlar: List<PdfSatiri>): Pair<File, Int> {
    val belge = PdfDocument()
    val genislik = (GENISLIK - 2 * KENAR).toInt()
    var sayfaNo = 0
    var sayfa: PdfDocument.Page? = null
    var y = 0f

    fun yeniSayfa() {
        sayfa?.let { belge.finishPage(it) }
        sayfaNo++
        sayfa = belge.startPage(PdfDocument.PageInfo.Builder(GENISLIK, YUKSEKLIK, sayfaNo).create())
        y = KENAR
        val alt = TextPaint(TextPaint.ANTI_ALIAS_FLAG).apply { textSize = 8f; color = Color.GRAY }
        sayfa!!.canvas.drawText("Foody · $sayfaNo", KENAR, YUKSEKLIK - 24f, alt)
    }

    fun boya(boyut: Float, kalin: Boolean, renk: Int) = TextPaint(TextPaint.ANTI_ALIAS_FLAG).apply {
        textSize = boyut
        color = renk
        typeface = Typeface.create(Typeface.SANS_SERIF, if (kalin) Typeface.BOLD else Typeface.NORMAL)
    }

    yeniSayfa()
    satirlar.forEach { s ->
        val (metin, boya, onBosluk, girinti) = when (s) {
            is PdfSatiri.Baslik -> Dortlu(s.metin, boya(20f, true, Color.rgb(22, 101, 52)), 0f, 0f)
            is PdfSatiri.AltYazi -> Dortlu(s.metin, boya(10f, false, Color.DKGRAY), 2f, 0f)
            is PdfSatiri.Bolum -> Dortlu(s.metin, boya(13f, true, Color.BLACK), 14f, 0f)
            is PdfSatiri.Ara -> Dortlu(s.metin, boya(10.5f, true, Color.DKGRAY), 6f, 0f)
            is PdfSatiri.Metin -> Dortlu(s.metin, boya(10.5f, false, Color.BLACK), 2f, 0f)
            is PdfSatiri.Madde -> Dortlu("•  ${s.metin}", boya(10.5f, false, Color.BLACK), 2f, 8f)
        }
        if (metin.isBlank()) return@forEach
        val yerlesim = StaticLayout.Builder.obtain(metin, 0, metin.length, boya, genislik - girinti.toInt())
            .setAlignment(Layout.Alignment.ALIGN_NORMAL).setLineSpacing(1.5f, 1f).build()
        // Bölüm başlığı sayfanın dibinde yalnız kalmasın.
        val gereken = onBosluk + yerlesim.height + if (s is PdfSatiri.Bolum) 40f else 0f
        if (y + gereken > YUKSEKLIK - KENAR) yeniSayfa() else y += onBosluk
        val tuval = sayfa!!.canvas
        tuval.save()
        tuval.translate(KENAR + girinti, y)
        yerlesim.draw(tuval)
        tuval.restore()
        y += yerlesim.height
    }
    sayfa?.let { belge.finishPage(it) }
    val klasor = File(baglam.cacheDir, "pdf").apply { mkdirs() }
    val dosya = File(klasor, "$ad.pdf")
    dosya.outputStream().use { belge.writeTo(it) }
    belge.close()
    return dosya to sayfaNo
}

private data class Dortlu(val metin: String, val boya: TextPaint, val onBosluk: Float, val girinti: Float)

/** "Foody menü 26 Eki" gibi bir ad: dosya adına uygun. */
fun pdfAdi(ad: String): String = ad.replace(Regex("[^\\p{L}\\p{N} _-]"), "").trim().replace(Regex("\\s+"), "_").ifBlank { "foody" }

fun pdfPaylas(baglam: Context, ad: String, satirlar: List<PdfSatiri>) {
    val (dosya, _) = pdfYaz(baglam, pdfAdi(ad), satirlar)
    val uri = FileProvider.getUriForFile(baglam, "${baglam.packageName}.dosyalar", dosya)
    val gonder = Intent(Intent.ACTION_SEND)
        .setType("application/pdf")
        .putExtra(Intent.EXTRA_STREAM, uri)
        .putExtra(Intent.EXTRA_SUBJECT, ad)
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    baglam.startActivity(Intent.createChooser(gonder, "$ad paylaş").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
}
