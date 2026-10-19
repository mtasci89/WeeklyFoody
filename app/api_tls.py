"""Uygulama API'si icin kendinden imzali sertifika ve baglanti kodu.

Alan adi olmadan (yalnizca IP ile) ucretsiz, gecerli bir sertifika almak
mumkun degil. Bu yuzden sunucu kendi sertifikasini uretir ve uygulama bu
sertifikanin ACIK ANAHTARINI sabitler (pin): telefon yalnizca bu anahtari
tasiyan sunucuyla konusur, araya giren biri sahte sertifikayla okuyamaz.

Baglanti kodu adresi, uygulama anahtarini ve pini tek satirda tasir; Telegram
`/uygulama` komutuyla yoneticiye gonderilir, uygulamada Ayarlar'a yapistirilir.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import secrets
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

CODE_PREFIX = "FOODY1."


def _san(host: str) -> str:
    try:
        ipaddress.ip_address(host)
        return f"IP:{host}"
    except ValueError:
        return f"DNS:{host}"


def ensure_certificate(cert: Path, key: Path, host: str) -> bool:
    """Sertifika yoksa uretir (10 yil, EC P-256). Uretildiyse True."""
    cert, key = Path(cert), Path(key)
    if cert.exists() and key.exists():
        return False
    cert.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-nodes", "-days", "3650", "-subj", "/CN=foody",
            "-addext", f"subjectAltName={_san(host)}",
            "-keyout", str(key), "-out", str(cert),
        ],
        check=True,
        capture_output=True,
    )
    key.chmod(0o600)
    return True


def spki_pin(cert: Path) -> str:
    """Sertifikanin acik anahtarinin (SubjectPublicKeyInfo, DER) SHA-256'si, base64.

    Android tarafi ayni degeri `cert.publicKey.encoded` uzerinden hesaplar."""
    pem = subprocess.run(
        ["openssl", "x509", "-pubkey", "-noout", "-in", str(cert)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    body = "".join(line for line in pem.splitlines() if line and not line.startswith("-----"))
    return base64.b64encode(hashlib.sha256(base64.b64decode(body)).digest()).decode()


def connection_code(url: str, token: str, pin: str) -> str:
    payload = json.dumps({"u": url.rstrip("/"), "t": token, "p": pin}, separators=(",", ":"))
    return CODE_PREFIX + base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def parse_connection_code(code: str) -> dict:
    """Testler ve teshis icin: kodu {u, t, p} sozlugune cevirir."""
    body = code.strip().removeprefix(CODE_PREFIX)
    body += "=" * (-len(body) % 4)
    return json.loads(base64.urlsafe_b64decode(body))


def host_of(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("Uygulama adresi https:// ile başlamalı, örn. https://152.67.69.25:8443")
    return parts.hostname


def update_env(path: Path, updates: dict[str, str]) -> None:
    """`.env` icinde verilen anahtarlari degistirir, olmayanlari sona ekler;
    diger satirlara dokunmaz."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(updates)
    for index, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in pending:
            lines[index] = f"{key}={pending.pop(key)}"
    lines += [f"{key}={value}" for key, value in pending.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def read_env_value(path: Path, key: str) -> str:
    path = Path(path)
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip()
    return ""


def prepare(env_path: Path, url: str, cert: Path, key: Path) -> dict:
    """Uygulama API'sini acmak icin gerekenleri hazirlar: anahtar (yoksa
    uretir), sertifika (yoksa uretir) ve `.env` ayarlari. Gizli deger dondurmez."""
    host = host_of(url)
    token = read_env_value(env_path, "APP_API_TOKEN")
    new_token = len(token) < 24
    if new_token:
        token = secrets.token_urlsafe(32)
    update_env(env_path, {"APP_API_ENABLED": "true", "APP_API_PUBLIC_URL": url.rstrip("/"), "APP_API_TOKEN": token})
    new_cert = ensure_certificate(cert, key, host)
    return {"yeni_anahtar": new_token, "yeni_sertifika": new_cert, "pin": spki_pin(cert)}
