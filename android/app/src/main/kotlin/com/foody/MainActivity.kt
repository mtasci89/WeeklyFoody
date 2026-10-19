package com.foody

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.viewmodel.compose.viewModel
import com.foody.ui.AnaViewModel
import com.foody.ui.FoodyTema
import com.foody.ui.Uygulama

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            FoodyTema { Uygulama(viewModel<AnaViewModel>()) }
        }
    }
}
