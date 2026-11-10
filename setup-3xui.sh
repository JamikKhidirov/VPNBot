#!/bin/bash
set -Eeuo pipefail

# ============================================================
#  Установка 3x-ui на VPN-сервер (Ubuntu 22.04 / 24.04)
#
#  Обычно этот скрипт не нужен: `python deploy.py` делает всё сам.
#  Он полезен, если хочешь поставить панель вручную на конкретный VPS.
#
#  Запуск:
#    sudo bash setup-3xui.sh
#    sudo PANEL_PORT=2053 PANEL_USER=admin PANEL_PASS='strongpass' VPN_PORT=443 bash setup-3xui.sh
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[x]${NC} $1"; exit 1; }

if [ "$EUID" -ne 0 ]; then
    err "Запусти с sudo: sudo bash setup-3xui.sh"
fi

PANEL_PORT="${PANEL_PORT:-2053}"
PANEL_USER="${PANEL_USER:-admin}"
PANEL_PASS="${PANEL_PASS:-$(openssl rand -base64 18 | tr -d '/+=' | head -c 20)}"
VPN_PORT="${VPN_PORT:-443}"
SSH_PORT="${SSH_PORT:-22}"

log "3x-ui: порт панели $PANEL_PORT, VPN-порт $VPN_PORT"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y curl wget ca-certificates ufw openssl jq

log "Настройка firewall..."
ufw allow "$SSH_PORT/tcp"  || true
ufw allow "$VPN_PORT/tcp"  || true
ufw allow "$VPN_PORT/udp"  || true
ufw allow "$PANEL_PORT/tcp" || true
ufw allow 80/tcp  || true
ufw allow 443/tcp || true
ufw --force enable || true

log "Включение BBR..."
grep -q '^net.core.default_qdisc=fq' /etc/sysctl.conf 2>/dev/null || echo 'net.core.default_qdisc=fq' >> /etc/sysctl.conf
grep -q '^net.ipv4.tcp_congestion_control=bbr' /etc/sysctl.conf 2>/dev/null || echo 'net.ipv4.tcp_congestion_control=bbr' >> /etc/sysctl.conf
sysctl -p >/dev/null 2>&1 || true

log "Установка 3x-ui..."
if ! command -v x-ui >/dev/null 2>&1 && [ ! -x /usr/local/x-ui/x-ui ]; then
    XUI_USERNAME="$PANEL_USER" \
    XUI_PASSWORD="$PANEL_PASS" \
    XUI_PORT="$PANEL_PORT" \
    XUI_DB_TYPE=sqlite \
    bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh) </dev/null || true
fi

XUI_BIN="$(command -v x-ui || true)"
if [ -z "$XUI_BIN" ] && [ -x /usr/local/x-ui/x-ui ]; then
    XUI_BIN=/usr/local/x-ui/x-ui
fi

if [ -n "$XUI_BIN" ] && [ -x "$XUI_BIN" ]; then
    "$XUI_BIN" setting -username "$PANEL_USER" -password "$PANEL_PASS" -port "$PANEL_PORT" || true
    "$XUI_BIN" setting -listenIP 0.0.0.0 || true
fi

systemctl enable x-ui >/dev/null 2>&1 || true
systemctl restart x-ui >/dev/null 2>&1 || true

log "Ожидание панели..."
PANEL_OK=0
for _ in $(seq 1 60); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PANEL_PORT}/login" || true)"
    if [ "$code" = "200" ]; then PANEL_OK=1; break; fi
    sleep 2
done

IP="$(curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}      3x-ui УСТАНОВЛЕНА${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  🌐 Панель:  http://${IP}:${PANEL_PORT}"
echo "  👤 Логин:   ${PANEL_USER}"
echo "  🔐 Пароль:  ${PANEL_PASS}"
echo "  🔌 VPN-порт: ${VPN_PORT}"
echo ""
if [ "$PANEL_OK" != "1" ]; then
    warn "Панель пока не ответила. Проверь: systemctl status x-ui"
fi
echo "  📌 Дальше — автоматически создать VLESS Reality inbound:"
echo "  1. На машине с ботом добавь сервер в servers.json:"
echo "       { \"ip\": \"${IP}\", \"password\": \"root-пароль\", \"location\": \"...\", \"name\": \"...\" }"
echo "  2. Запусти: python deploy.py --deploy --no-run"
echo "     (или в боте: /sync_servers, если inbound уже есть)"
echo ""
