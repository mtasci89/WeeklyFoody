package com.foody.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TakvimEkran(vm: AnaViewModel, geri: () -> Unit, tarifAc: (String) -> Unit) {
    var tarih by rememberSaveable { mutableStateOf(LocalDate.now().toString()) }
    var sec by remember { mutableStateOf(false) }
    val durum by vm.gunYemekleri.collectAsStateWithLifecycle()
    LaunchedEffect(tarih) { vm.gunYemekleriniGetir(tarih) }
    Column(Modifier.fillMaxSize()) {
        Baslik("Yemek takvimi", tarih, geri = geri) {
            IconButton(onClick = { sec = true }) { Icon(Icons.Rounded.CalendarMonth, "Tarih seç") }
        }
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            TextButton(onClick = { tarih = LocalDate.parse(tarih).minusDays(1).toString() }) { Text("Önceki gün") }
            TextButton(onClick = { tarih = LocalDate.now().toString() }) { Text("Bugün") }
            TextButton(onClick = { tarih = LocalDate.parse(tarih).plusDays(1).toString() }) { Text("Sonraki gün") }
        }
        Text("Cal Track ile aynı tarihli onaylı menü. Yediklerin Cal Track'te ayrıca seçilir.", Modifier.padding(16.dp))
        DurumKarti(durum.yukleniyor, durum.hata, yenile = { vm.gunYemekleriniGetir(tarih) })
        if (!durum.yukleniyor && durum.hata == null && durum.veri?.yemekler?.isEmpty() == true) {
            Text("Bu tarih için onaylı yemek yok.", Modifier.padding(16.dp))
        }
        LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(durum.veri?.takeIf { it.tarih == tarih }?.yemekler.orEmpty(), key = { it.id }) { yemek ->
                Kart(Modifier.fillMaxWidth()) {
                    Text(yemek.ad)
                    if (yemek.haftalik) Text("Haftalık meze")
                    yemek.kcal?.let { Text("${it.toInt()} kcal / porsiyon${if (yemek.tahmini == true) " · tahmini" else ""}") }
                    TextButton(onClick = { tarifAc(yemek.id) }) { Text("Tarifi aç") }
                }
            }
        }
    }
    if (sec) {
        val picker = rememberDatePickerState(initialSelectedDateMillis = LocalDate.parse(tarih).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli())
        DatePickerDialog(onDismissRequest = { sec = false }, confirmButton = {
            TextButton(onClick = {
                picker.selectedDateMillis?.let { tarih = Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString() }
                sec = false
            }) { Text("Seç") }
        }, dismissButton = { TextButton(onClick = { sec = false }) { Text("Vazgeç") } }) { DatePicker(picker) }
    }
}
