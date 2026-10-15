#!/usr/bin/env bash
# Sunucudaki botun son gunluk satirlari (gizli degerler maskelenir). Mac'ten:
#   ./deploy/sunucu-gunluk.sh        # son 40 satir
#   ./deploy/sunucu-gunluk.sh 200    # son 200 satir
set -euo pipefail
KEY="${WEEKLYFOODY_SSH_KEY:-$HOME/Downloads/ssh-key-weeklyfoody1GB.key}"
SRV="${WEEKLYFOODY_SERVER:-opc@152.67.69.25}"
LINES="${1:-40}"
ssh -i "$KEY" "$SRV" "echo \"durum: \$(systemctl is-active weeklyfoody)\"; sudo journalctl -u weeklyfoody -n $LINES --no-pager" \
  | sed -E 's/[0-9]{8,10}:[A-Za-z0-9_-]{30,}/[TOKEN]/g; s/AIza[0-9A-Za-z_-]{20,}/[KEY]/g'
