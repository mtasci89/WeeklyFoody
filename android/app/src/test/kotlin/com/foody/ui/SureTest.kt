package com.foody.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class SureTest {
    @Test fun gecenSureOkunurBicimde() {
        assertEquals("0 sn", gecenSure(1_000, 500))
        assertEquals("42 sn", gecenSure(0, 42_000))
        assertEquals("1 dk 05 sn", gecenSure(0, 65_000))
    }
}
