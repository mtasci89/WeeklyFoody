#!/usr/bin/env bash
# Foody Android uygulamasi icin sunucudaki HTTPS API'yi bir kez acar. Mac'ten:
#   ./deploy/uygulama-ac.sh
# Once kodu gunceller, sonra anahtar + sertifika uretir (varsa korur), guvenlik
# duvarinda 8443'u acar, botu yeniden baslatir ve disaridan erisimi dener.
# Gizli deger (anahtar, token) ekrana yazilmaz.
set -euo pipefail
KEY="${WEEKLYFOODY_SSH_KEY:-$HOME/Downloads/ssh-key-weeklyfoody1GB.key}"
SRV="${WEEKLYFOODY_SERVER:-opc@152.67.69.25}"
HOST="${SRV#*@}"
PORT="${FOODY_API_PORT:-8443}"
ADRES="https://$HOST:$PORT"
DIR="$(cd "$(dirname "$0")" && pwd)"

"$DIR/sunucu-guncelle.sh"

ssh -i "$KEY" "$SRV" "ADRES=$ADRES PORT=$PORT bash -s" <<'EOF'
set -e
cd /home/opc/WeeklyFoody
echo "== uygulama API'si hazirlaniyor"
.venv/bin/python -m app.cli uygulama-hazirla --adres "$ADRES"
if systemctl is-active -q firewalld; then
  sudo firewall-cmd -q --permanent --add-port=$PORT/tcp && sudo firewall-cmd -q --reload
  echo "guvenlik duvari: $PORT/tcp acik"
fi
sudo systemctl restart weeklyfoody
sleep 15
echo "durum: $(systemctl is-active weeklyfoody)"
sudo journalctl -u weeklyfoody --since "-20 sec" --no-pager | grep -E "app_api|application_started|ERROR" \
  | sed -E 's/[0-9]{8,10}:[A-Za-z0-9_-]{30,}/[TOKEN]/g; s/AIza[0-9A-Za-z_-]{20,}/[KEY]/g' || true
echo "sunucunun icinden deneme (401 beklenir): $(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1:$PORT/api/v1/durum)"
EOF

echo "== Mac'ten (internet uzerinden) deneme"
KOD=$(curl -sk -m 10 -o /dev/null -w '%{http_code}' "$ADRES/api/v1/durum" || true)
if [ "$KOD" = "401" ]; then
  echo "TAMAM: $ADRES disaridan erisilebilir. Telegram'da botuna /uygulama yaz ve kodu uygulamaya yapistir."
else
  echo "ULASILAMADI (kod: ${KOD:-yok}). Oracle'da $PORT portu kapali olabilir:"
  echo "  Oracle Cloud > Networking > Virtual cloud networks > (VCN) > Security Lists > Default Security List"
  echo "  > Add Ingress Rules: Source CIDR 0.0.0.0/0, IP Protocol TCP, Destination Port Range $PORT"
  echo "Kuralı ekleyip bu betigi tekrar calistir."
fi
