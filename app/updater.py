"""Sunucunun kendini telefondan güncellemesi (Telegram /guncelle, uygulama düğmesi).

Güncelleme `deploy/kendini-guncelle.sh` ile botun DIŞINDA, `systemd-run` ile açılan
ayrı bir görevde yürür: betik sonunda servisi yeniden başlattığında kendisi de
öldürülmesin. Yeni bot açılırken `data/guncelleme.json` işaretini görür ve
yöneticiye ne değiştiğini bildirir.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "deploy" / "kendini-guncelle.sh"
MARKER = REPO / "data" / "guncelleme.json"
# Aynı anda iki güncelleme başlamasın; takılı kalan bir işaret 15 dk sonra yok sayılır.
STALE_SECONDS = 15 * 60


def current_version(repo: Path = REPO) -> dict:
    """{"surum": kısa sha, "aciklama": commit başlığı}; git yoksa "bilinmiyor"."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%h%x1f%s"],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        sha, _, subject = out.partition("\x1f")
        return {"surum": sha, "aciklama": subject}
    except Exception:
        return {"surum": "bilinmiyor", "aciklama": ""}


def update_running(marker: Path = MARKER) -> bool:
    try:
        started = json.loads(marker.read_text(encoding="utf-8")).get("zaman", 0)
    except (OSError, ValueError):
        return False
    return time.time() - started < STALE_SECONDS


def start_update(chat_id: int | None, *, marker: Path = MARKER, runner=subprocess.run) -> str:
    """Güncellemeyi başlatır ve hemen döner. Kullanıcıya gösterilecek metni döndürür."""
    if update_running(marker):
        return "Bir güncelleme zaten sürüyor; birkaç dakika içinde sonucu bildireceğim."
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"chat_id": chat_id, "onceki": current_version()["surum"], "zaman": time.time()}),
        encoding="utf-8",
    )
    command = [
        "sudo", "-n", "systemd-run",
        f"--unit=foody-guncelle-{int(time.time())}", "--collect",
        "--uid=opc", "--gid=opc", f"--property=WorkingDirectory={REPO}",
        # SELinux: ev klasöründeki betik doğrudan çalıştırılamaz; /bin/bash okur.
        "/bin/bash", str(SCRIPT),
    ]
    try:
        runner(command, check=True, capture_output=True, text=True, timeout=30)
    except Exception as error:
        marker.unlink(missing_ok=True)
        detail = getattr(error, "stderr", "") or str(error)
        logger.error("update_start_failed detail=%s", str(detail)[:300])
        return f"Güncelleme başlatılamadı: {str(detail)[:200]}"
    logger.info("update_started")
    return "Güncelleme başladı. 1-3 dakika içinde bot yeniden açılıp sonucu bildirecek."


def pending_notice(marker: Path = MARKER) -> tuple[int | None, str] | None:
    """Açılışta: bir güncellemeden sonra mı açıldık? (chat_id, mesaj) ya da None."""
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    marker.unlink(missing_ok=True)
    now = current_version()
    if now["surum"] == data.get("onceki"):
        return data.get("chat_id"), f"ℹ️ Bot yeniden açıldı, sürüm değişmedi ({now['surum']})."
    return data.get("chat_id"), f"✅ Sunucu güncellendi: {data.get('onceki')} → {now['surum']}\n{now['aciklama']}"
