"""Sunucunun kendini telefondan güncellemesi: app/updater.py ve deploy/kendini-guncelle.sh."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from app import updater

ROOT = Path(__file__).resolve().parents[1]


# --- app/updater.py ---------------------------------------------------------------


def test_current_version_reads_git():
    version = updater.current_version()
    assert len(version["surum"]) >= 7 and version["aciklama"]


def test_current_version_without_git(tmp_path):
    assert updater.current_version(tmp_path)["surum"] == "bilinmiyor"


def test_start_update_runs_the_script_outside_the_service(tmp_path):
    marker = tmp_path / "guncelleme.json"
    calls = []

    message = updater.start_update(42, marker=marker, runner=lambda cmd, **kw: calls.append(cmd))

    assert "Güncelleme başladı" in message
    cmd = calls[0]
    assert cmd[:3] == ["sudo", "-n", "systemd-run"]
    assert "--uid=opc" in cmd and "--collect" in cmd
    # SELinux: betik doğrudan değil /bin/bash ile çalıştırılır.
    assert cmd[-2:] == ["/bin/bash", str(updater.SCRIPT)]
    data = json.loads(marker.read_text())
    assert data["chat_id"] == 42 and data["onceki"] == updater.current_version()["surum"]


def test_second_update_while_one_is_running_is_refused(tmp_path):
    marker = tmp_path / "guncelleme.json"
    calls = []
    updater.start_update(1, marker=marker, runner=lambda cmd, **kw: calls.append(cmd))

    assert "zaten sürüyor" in updater.start_update(1, marker=marker, runner=lambda cmd, **kw: calls.append(cmd))
    assert len(calls) == 1


def test_stale_marker_does_not_block_forever(tmp_path):
    marker = tmp_path / "guncelleme.json"
    marker.write_text(json.dumps({"zaman": time.time() - updater.STALE_SECONDS - 5}))

    assert not updater.update_running(marker)


def test_failed_start_reports_and_clears_the_marker(tmp_path):
    marker = tmp_path / "guncelleme.json"

    def boom(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd, stderr="sudo: a password is required")

    message = updater.start_update(1, marker=marker, runner=boom)

    assert "başlatılamadı" in message and "password" in message
    assert not marker.exists()


def test_startup_notice_after_an_update(tmp_path):
    marker = tmp_path / "guncelleme.json"
    marker.write_text(json.dumps({"chat_id": 7, "onceki": "eski123", "zaman": time.time()}))

    chat_id, text = updater.pending_notice(marker)

    assert chat_id == 7
    assert text.startswith("✅ Sunucu güncellendi: eski123 → ")
    assert not marker.exists()
    assert updater.pending_notice(marker) is None


def test_startup_notice_when_nothing_changed(tmp_path):
    marker = tmp_path / "guncelleme.json"
    marker.write_text(json.dumps({"chat_id": 7, "onceki": updater.current_version()["surum"]}))

    assert "değişmedi" in updater.pending_notice(marker)[1]


# --- deploy/kendini-guncelle.sh: gerçek git, sahte python ve sudo ------------------------


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture()
def server(tmp_path):
    """origin (bare) + sunucudaki çalışma kopyası; python ve sudo komutları kaydedilir."""
    origin, seed, work, home, bin_dir = (tmp_path / n for n in ("origin.git", "seed", "work", "home", "bin"))
    for d in (seed, home, bin_dir):
        d.mkdir()
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    (seed / "deploy").mkdir()
    shutil.copy(ROOT / "deploy" / "kendini-guncelle.sh", seed / "deploy" / "kendini-guncelle.sh")
    (seed / "requirements.txt").write_text("")
    (seed / ".gitignore").write_text("data/\n.venv/\n")
    for args in (("init", "-q", "-b", "main"), ("add", "."), ("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "ilk"),
                 ("remote", "add", "origin", str(origin)), ("push", "-q", "-u", "origin", "main")):
        _git(seed, *args)
    _git(tmp_path, "clone", "-q", "-b", "main", str(origin), str(work))
    (work / "data").mkdir()
    (work / "data" / "mealplanner.db").write_text("db")
    (work / "data" / "guncelleme.json").write_text("{}")
    log = tmp_path / "log"
    (work / ".venv" / "bin").mkdir(parents=True)
    fake_py = work / ".venv" / "bin" / "python"
    fake_py.write_text(f'#!/bin/bash\necho "python $*" >> {log}\n')
    fake_sudo = bin_dir / "sudo"
    fake_sudo.write_text(f'#!/bin/bash\necho "sudo $*" >> {log}\n')
    for f in (fake_py, fake_sudo):
        f.chmod(0o755)
    env = {**os.environ, "HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    def run():
        result = subprocess.run(["/bin/bash", str(work / "deploy" / "kendini-guncelle.sh")],
                                env=env, capture_output=True, text=True, timeout=60)
        return result, (log.read_text() if log.exists() else "")

    return {"seed": seed, "work": work, "home": home, "run": run}


def _new_commit(seed, name="yeni.txt"):
    (seed / name).write_text("x")
    _git(seed, "add", ".")
    _git(seed, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "yeni özellik")
    _git(seed, "push", "-q")


def test_script_says_up_to_date_and_does_not_restart(server):
    result, log = server["run"]()

    assert result.returncode == 0
    assert "zaten güncel" in log
    assert "systemctl" not in log
    assert list((server["home"] / "yedekler").glob("mealplanner-*.db"))  # önce yedek
    assert not (server["work"] / "data" / "guncelleme.json").exists()


def test_script_updates_relabels_and_restarts(server):
    _new_commit(server["seed"])

    result, log = server["run"]()

    assert result.returncode == 0, result.stdout + result.stderr
    assert (server["work"] / "yeni.txt").exists()
    lines = log.splitlines()
    assert any(line.startswith("python -m pip install") for line in lines)
    assert any("import app.agent.runner" in line for line in lines)
    assert "sudo -n chcon -R -h -t bin_t .venv/bin" in lines
    assert lines[-1] == "sudo -n systemctl restart weeklyfoody"
    assert (server["work"] / "data" / "guncelleme.json").exists()  # yeni bot okuyup bildirecek


def test_script_failure_notifies_and_keeps_the_old_service(server):
    _new_commit(server["seed"])
    # Sunucuda yerel bir commit: ff-only çekme başarısız olur.
    (server["work"] / "yerel.txt").write_text("y")
    _git(server["work"], "add", "yerel.txt")
    _git(server["work"], "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "yerel")

    result, log = server["run"]()

    assert result.returncode == 1
    assert "güncellenemedi (adım: git pull)" in log
    assert "systemctl" not in log
    assert not (server["work"] / "data" / "guncelleme.json").exists()
