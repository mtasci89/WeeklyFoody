package com.foody.ui

import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Menüdeki seçim gerekçesi ve gerçek tarifin tarayıcıda açılan kaynak bağlantısı. */
@Composable
fun TarifAciklamasi(kaynak: String, neden: String) {
    val uriHandler = LocalUriHandler.current
    val context = LocalContext.current
    val uri = runCatching { Uri.parse(kaynak) }.getOrNull()
    val acilabilir = uri?.scheme == "https" && !uri?.host.isNullOrBlank()
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        if (neden.isNotBlank()) {
            BolumBasligi("Neden bu yemek?")
            Text(neden, fontSize = 14.sp, lineHeight = 20.sp, color = Renk.Murekkep)
        }
        if (acilabilir) TextButton(onClick = {
            runCatching { uriHandler.openUri(kaynak) }.onFailure {
                Toast.makeText(context, "Kaynak bağlantısı açılamadı.", Toast.LENGTH_SHORT).show()
            }
        }) { Text("Tarifin kaynağını aç · ${uri?.host}") }
        else if (kaynak.isNotBlank()) Text("Kaynak: $kaynak", fontSize = 12.sp, color = Renk.Soluk)
    }
}
