package com.foody.data

import android.content.Context
import android.graphics.Bitmap
import android.graphics.ImageDecoder
import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.util.Base64

/** Asistana gönderilmeye hazır görsel: küçültülmüş JPEG ve ekranda gösterilecek önizleme. */
class Ek(val id: Long, val veri: ByteArray, val onizleme: Bitmap) {
    val mime get() = "image/jpeg"
    val base64: String get() = Base64.getEncoder().encodeToString(veri)
}

object Gorsel {
    /** En uzun kenar: yazıların okunması için yeterli, göndermek için küçük (~300-600 KB). */
    const val EN_UZUN = 1600
    const val EN_COK = 4

    /** Oranı koruyarak en uzun kenarı [enUzun]'u geçmeyen boyut. */
    fun olcek(genislik: Int, yukseklik: Int, enUzun: Int = EN_UZUN): Pair<Int, Int> {
        val buyuk = maxOf(genislik, yukseklik)
        if (buyuk <= enUzun || buyuk <= 0) return genislik to yukseklik
        val oran = enUzun.toDouble() / buyuk
        return maxOf(1, (genislik * oran).toInt()) to maxOf(1, (yukseklik * oran).toInt())
    }

    fun jpeg(bitmap: Bitmap, kalite: Int = 85): ByteArray =
        ByteArrayOutputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, kalite, it); it.toByteArray() }

    /** Seçilen ya da çekilen fotoğrafı okur, küçültür, JPEG'e çevirir. */
    suspend fun hazirla(context: Context, uri: Uri, id: Long): Ek = withContext(Dispatchers.Default) {
        val kaynak = ImageDecoder.createSource(context.contentResolver, uri)
        val bitmap = ImageDecoder.decodeBitmap(kaynak) { cozucu, bilgi, _ ->
            val (g, y) = olcek(bilgi.size.width, bilgi.size.height)
            cozucu.setTargetSize(g, y)
            cozucu.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
        }
        val (og, oy) = olcek(bitmap.width, bitmap.height, 240)
        Ek(id, jpeg(bitmap), Bitmap.createScaledBitmap(bitmap, og, oy, true))
    }
}
