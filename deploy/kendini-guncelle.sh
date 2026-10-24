#!/usr/bin/env bash
# Sunucuda calisir: botu GitHub'daki son koda gunceller. Telegram /guncelle ya da
# uygulamadaki "Sunucuyu guncelle" dugmesi bunu botun DISINDA, ayri bir systemd
# gorevi olarak baslatir (app/updater.py); bot yeniden baslarken yarida kalmaz.
#
# Sonuc yoneticiye Telegram'dan bildirilir: basariliysa yeni bot acilista
# ("Guncellendi: ..."), basarisizsa bu betik (`app.cli bildir`). Bir adim
# basarisiz olursa servis yeniden baslatilmaz; eski surum calismaya devam eder.
#
# Tum govde bir fonksiyonda: `git pull` bu dosyayi degistirse bile bash calisan
# kopyayi bastan sona okumus olur.
set -uo pipefail

main() {
    cd "$(dirname "$0")/.." || exit 1
    local py=.venv/bin/python
    local adim=""

    fail() {
        echo "guncelleme_basarisiz adim=$adim"
        rm -f data/guncelleme.json
        "$py" -m app.cli bildir "⚠️ Sunucu güncellenemedi (adım: $adim). Eski sürüm çalışmaya devam ediyor. Ayrıntı: ./deploy/sunucu-gunluk.sh" || true
        exit 1
    }

    adim="yedek"
    mkdir -p ~/yedekler && cp -a data/mealplanner.db ~/yedekler/mealplanner-$(date +%Y%m%d-%H%M).db || fail
    find ~/yedekler -name 'mealplanner-*.db' -mtime +30 -delete

    local onceki
    onceki=$(git rev-parse --short HEAD)
    adim="git pull"
    git pull -q --ff-only || fail
    if [ "$(git rev-parse --short HEAD)" = "$onceki" ]; then
        rm -f data/guncelleme.json
        "$py" -m app.cli bildir "✅ Sunucu zaten güncel ($onceki)." || true
        exit 0
    fi

    adim="kütüphaneler"
    "$py" -m pip install -q --no-cache-dir -r requirements.txt || fail
    adim="kod denetimi"
    "$py" -c "import app.agent.runner, app.bot.telegram, app.scheduler.weekly, app.api" || fail
    # SELinux: ev klasorundeki programlari servis calistiramaz (PROJE.md / DEVIR.md).
    adim="SELinux etiketi"
    sudo -n chcon -R -h -t bin_t .venv/bin || fail
    echo "guncelleme_yeniden_baslatiliyor $onceki -> $(git rev-parse --short HEAD)"
    sudo -n systemctl restart weeklyfoody
}

main "$@"
exit $?
