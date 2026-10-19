"""API'nin cevap bicimi Android ornekleriyle ayni mi?

Uygulama `android/app/src/test/resources/ornek/*.json` dosyalarina gore
yazildi ve test edildi. Bir alan adi degisir ya da kaybolursa uygulama sessizce
bos ekran gosterir; bu test onu burada yakalar. Bilerek degistirdiysen
ornekleri yeniden uret: `python -m tests.app_samples android/app/src/test/resources/ornek`
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.app_samples import build_samples

SAMPLES = Path(__file__).resolve().parents[1] / "android/app/src/test/resources/ornek"


def shape(value):
    """Degerler degil, yalnizca anahtarlar ve tipler (null her seyle uyumlu)."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return None


def compatible(expected, actual) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and expected.keys() == actual.keys() and all(
            compatible(expected[k], actual[k]) for k in expected
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and (not expected or not actual or compatible(expected[0], actual[0]))
    return True


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    return build_samples(tmp_path_factory.mktemp("ornek"))


@pytest.mark.parametrize("name", sorted(p.stem for p in SAMPLES.glob("*.json")))
def test_api_still_matches_the_android_samples(live, name):
    stored = json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))

    assert compatible(shape(stored), shape(live[name])), f"{name}.json API cevabıyla uyuşmuyor"
