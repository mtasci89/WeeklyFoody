package com.foody.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController

private val ALT_MENU = setOf("menu", "alisveris", "tarifler", "kurallar")

@Composable
fun Uygulama(vm: AnaViewModel) {
    val nav = rememberNavController()
    val giris by nav.currentBackStackEntryAsState()
    val rota = giris?.destination?.route.orEmpty()
    val bilgi by vm.bilgi.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(bilgi) {
        bilgi?.let { snackbar.showSnackbar(it); vm.bilgiGosterildi() }
    }

    Scaffold(
        containerColor = Renk.Arka,
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            if (rota in ALT_MENU) Column(Modifier.navigationBarsPadding()) {
                HorizontalDivider(color = Renk.Cizgi)
                AltMenu(secili = rota, sec = { hedef -> nav.ustDuzey(hedef) })
            }
        },
    ) { ic ->
        NavHost(nav, startDestination = "menu", modifier = Modifier.fillMaxSize().padding(ic)) {
            composable("menu") {
                MenuEkran(
                    vm,
                    tarifAc = { id -> nav.navigate("tarif/$id") },
                    ayarlar = { nav.navigate("ayarlar") },
                )
            }
            composable("alisveris") { AlisverisEkran(vm) }
            composable("tarifler") { TariflerEkran(vm, tarifAc = { id -> nav.navigate("tarif/$id") }) }
            composable("kurallar") { KurallarEkran(vm) }
            composable("tarif/{id}") { e -> TarifEkran(vm, e.arguments?.getString("id").orEmpty(), geri = { nav.popBackStack() }) }
            composable("ayarlar") {
                AyarlarEkran(vm, geri = { nav.popBackStack() })
            }
        }
    }
}

/** Alt menü hedefine gider; yığını şişirmez. */
private fun NavHostController.ustDuzey(hedef: String) {
    navigate(hedef) {
        popUpTo(graph.startDestinationId) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}
