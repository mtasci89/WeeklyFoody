package com.foody.data

import android.content.Context

/** Alışveriş listesinde alınanlar: yalnızca bu telefonda, hafta başına tutulur (gizli değil). */
class Isaretler(context: Context) {
    private val prefs = context.getSharedPreferences("foody_alisveris", Context.MODE_PRIVATE)

    fun oku(hafta: String): Set<String> = prefs.getStringSet(anahtar(hafta), emptySet()).orEmpty().toSet()

    fun yaz(hafta: String, isaretli: Set<String>) {
        prefs.edit().apply {
            // Yalnızca son birkaç haftayı tut.
            prefs.all.keys.filter { it.startsWith("hafta_") }.sorted().dropLast(3).forEach { remove(it) }
            putStringSet(anahtar(hafta), isaretli)
        }.apply()
    }

    private fun anahtar(hafta: String) = "hafta_$hafta"
}
