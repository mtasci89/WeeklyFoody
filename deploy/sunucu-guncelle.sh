#!/usr/bin/env bash
# Oracle sunucusundaki botu GitHub'daki son koda gunceller. Mac'ten calistirilir:
#   ./deploy/sunucu-guncelle.sh
# Once veritabaninin yedegini alir; hata olursa servis eski haliyle kalir.
set -euo pipefail
KEY="${WEEKLYFOODY_SSH_KEY:-$HOME/Downloads/ssh-key-weeklyfoody1GB.key}"
SRV="${WEEKLYFOODY_SERVER:-opc@152.67.69.25}"

ssh -i "$KEY" "$SRV" 'bash -s' <<'EOF'
set -e
cd /home/opc/WeeklyFoody
STAMP=$(date +%Y%m%d-%H%M)
mkdir -p ~/yedekler
cp -a data/mealplanner.db ~/yedekler/mealplanner-$STAMP.db
find ~/yedekler -name 'mealplanner-*.db' -mtime +30 -delete
echo "yedek: ~/yedekler/mealplanner-$STAMP.db"
git pull -q --ff-only
git log --oneline -1
.venv/bin/pip install -q --no-cache-dir -r requirements.txt
.venv/bin/python -c "import app.agent.runner, app.bot.telegram, app.scheduler.weekly" 
# SELinux: ev klasorundeki programlari servis calistiramaz; yeni kurulan
# dosyalar da "calistirilabilir" etiketi almali.
sudo chcon -R -h -t bin_t .venv/bin
sudo systemctl restart weeklyfoody
sleep 15
echo "durum: $(systemctl is-active weeklyfoody)"
sudo journalctl -u weeklyfoody --since "-20 sec" --no-pager | tail -8 \
  | sed -E 's/[0-9]{8,10}:[A-Za-z0-9_-]{30,}/[TOKEN]/g; s/AIza[0-9A-Za-z_-]{20,}/[KEY]/g'
EOF
