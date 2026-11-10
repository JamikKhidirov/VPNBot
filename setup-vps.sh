#!/bin/bash
set -Eeuo pipefail

# ============================================================
#  VPNBot — установка бота на VPS (Ubuntu 22.04 / 24.04)
#  Запуск:  sudo bash setup-vps.sh
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[x]${NC} $1"; exit 1; }

if [ "$EUID" -ne 0 ]; then
    err "Запусти с sudo: sudo bash setup-vps.sh"
fi

REPO_URL="${REPO_URL:-https://github.com/JamikKhidirov/VPNBot.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/vpnbot}"
PUBLIC_IP="$(curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"

log "Публичный IP: ${PUBLIC_IP:-не определён}"

# ── 1. Системные пакеты ─────────────────────────────────────
log "Обновление системы и установка зависимостей..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl git ufw docker.io docker-compose-plugin

systemctl enable --now docker

# ── 2. Firewall ─────────────────────────────────────────────
log "Настройка firewall..."
ufw allow 22/tcp    || true
ufw allow 80/tcp    || true
ufw allow 443/tcp   || true
ufw allow 9090/tcp  || true
ufw allow 8080/tcp  || true
ufw --force enable  || true

# ── 3. Код проекта ──────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
    INSTALL_DIR="$SCRIPT_DIR"
    log "Использую текущую папку: $INSTALL_DIR"
elif [ -d "$INSTALL_DIR/.git" ]; then
    log "Обновляю репозиторий в $INSTALL_DIR..."
    git -C "$INSTALL_DIR" pull --ff-only || warn "Git pull не удался, продолжаю с текущей версией"
else
    log "Клонирую $REPO_URL → $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ── 4. .env ─────────────────────────────────────────────────
if [ ! -f .env ]; then
    cp .env.example .env
    log "Создан .env из .env.example"
fi

if [ -n "$PUBLIC_IP" ]; then
    grep -q '^SUB_DOMAIN=' .env && sed -i "s|^SUB_DOMAIN=.*|SUB_DOMAIN=http://${PUBLIC_IP}:9090|" .env || echo "SUB_DOMAIN=http://${PUBLIC_IP}:9090" >> .env
    grep -q '^DEFAULT_SERVER_HOST=' .env && sed -i "s|^DEFAULT_SERVER_HOST=.*|DEFAULT_SERVER_HOST=${PUBLIC_IP}|" .env || echo "DEFAULT_SERVER_HOST=${PUBLIC_IP}" >> .env
fi

# SQLite — самый простой вариант
grep -q '^DB_URL=' .env || echo "DB_URL=sqlite+aiosqlite:///./vpnbot.db" >> .env

touch vpnbot.db

# ── 5. Запуск ───────────────────────────────────────────────
log "Сборка и запуск контейнеров..."
docker compose up -d --build

# ── 6. Итог ─────────────────────────────────────────────────
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}      VPNBot УСТАНОВЛЕН!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  🤖 Бот:        запущен в Docker"
echo -e "  🌐 VPS:        ${PUBLIC_IP:-?}"
echo -e "  🔗 Подписки:   http://${PUBLIC_IP:-IP}:9090/sub/<token>"
echo ""
echo -e "${YELLOW}  Что сделать дальше:${NC}"
echo "  1. Открой .env и впиши BOT_TOKEN, ADMIN_IDS, WALLET_ADDRESS:"
echo "       nano $INSTALL_DIR/.env"
echo "  2. Перезапусти бота:"
echo "       cd $INSTALL_DIR && docker compose restart"
echo "  3. Создай VPN-серверы (на других VPS):"
echo "       заполни servers.json и запусти: python deploy.py --deploy --no-run"
echo "  4. В Telegram: /admin → проверь серверы и тарифы"
echo ""
echo -e "  Токены:"
echo "  • BOT_TOKEN       — https://t.me/BotFather"
echo "  • WALLET_ADDRESS  — USDT TRC20 кошелёк"
echo "  • YOOKASSA        — https://yookassa.ru"
echo "  • CRYPTOBOT_TOKEN — https://t.me/CryptoBot"
echo ""
