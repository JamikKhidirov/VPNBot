#!/bin/bash
set -e

# ============================================================
# VPNBot — полная установка на VPS (Ubuntu 22.04 / 24.04)
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[x]${NC} $1"; exit 1; }

# --- Проверка прав ---
if [ "$EUID" -ne 0 ]; then
    err "Запусти с sudo: sudo bash setup-vps.sh"
fi

# --- 1. Системные зависимости ---
log "Обновление системы..."
apt update && apt upgrade -y

log "Установка зависимостей..."
apt install -y curl wget git ufw docker.io docker-compose-plugin \
    certbot python3-certbot-nginx nginx postgresql-client redis-tools

systemctl enable --now docker

# --- 2. Настройка firewall ---
log "Настройка firewall..."
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 8080/tcp
ufw --force enable

# --- 3. Установка 3x-ui (X-UI Panel) ---
log "Установка 3x-ui панели управления..."
bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)

log "3x-ui установлена. Открой браузер: http://$(curl -s ifconfig.me):2053"
warn "Логин по умолчанию: admin | Пароль: admin"
warn "ОБЯЗАТЕЛЬНО смени пароль после входа!"

# --- 4. Установка PostgreSQL через Docker ---
log "Установка PostgreSQL..."
docker run -d \
    --name vpnbot-db \
    --restart unless-stopped \
    -e POSTGRES_USER=vpnbot \
    -e POSTGRES_PASSWORD=$(openssl rand -base64 16) \
    -e POSTGRES_DB=vpnbot \
    -p 127.0.0.1:5432:5432 \
    -v pgdata:/var/lib/postgresql/data \
    postgres:16-alpine

DB_PASS=$(docker inspect vpnbot-db | grep POSTGRES_PASSWORD | head -1 | cut -d= -f2 | cut -d'"' -f1)

# --- 5. Установка Redis ---
log "Установка Redis..."
docker run -d \
    --name vpnbot-redis \
    --restart unless-stopped \
    -p 127.0.0.1:6379:6379 \
    redis:7-alpine

# --- 6. Загрузка бота ---
log "Загрузка VPNBot..."
cd /opt
git clone https://github.com/YOUR_REPO/vpnbot.git || warn "Репозиторий не найден, создаём вручную..."
mkdir -p /opt/vpnbot
cd /opt/vpnbot

# --- 7. Создание .env ---
log "Создание конфигурации .env..."
cat > /opt/vpnbot/.env << 'ENVEOF'
# === Telegram ===
BOT_TOKEN=ЗАМЕНИ_НА_ТОКЕН_ОТ_BOTFATHER
ADMIN_IDS=1819756249

# === База данных ===
DB_URL=postgresql+asyncpg://vpnbot:ПАРОЛЬ_ИЗ_ШАГА_4@localhost:5432/vpnbot
REDIS_URL=redis://localhost:6379/0

# === ЮKassa (https://yookassa.ru) ===
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
YOOKASSA_RETURN_URL=https://t.me/НАЗВАНИЕ_БОТА

# === CryptoBot (https://t.me/CryptoBot) ===
CRYPTOBOT_TOKEN=

# === Пробный период ===
TRIAL_DAYS=5

# === V2Ray / 3x-ui API ===
# URL панели 3x-ui (замени на свой)
V2RAY_API_URL=http://localhost:2053/panel/api/inbounds
# API-ключ (если включена авторизация в 3x-ui)
V2RAY_API_KEY=

# === Сервер по умолчанию ===
DEFAULT_SERVER_HOST=ЗАМЕНИ_НА_IP_ВПС
DEFAULT_SERVER_PORT=443
DEFAULT_PROTOCOL=vless

# === Webhook (оставь пустым для polling) ===
WEBHOOK_HOST=
WEBHOOK_PORT=8080
WEBHOOK_SECRET=

PAYMENT_PROVIDER=yookassa
ENVEOF

log "Файл .env создан! Отредактируй его: nano /opt/vpnbot/.env"

# --- 8. Запуск бота через Docker ---
log "Сборка и запуск бота..."
cd /opt/vpnbot
docker compose up -d --build

# --- Итог ---
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}      VPNBot УСТАНОВЛЕН!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  🌐 3x-ui панель:    http://$(curl -s ifconfig.me):2053"
echo "  🤖 Telegram бот:    запущен в Docker"
echo ""
echo "  📝 Что нужно сделать вручную:"
echo "  1. Отредактируй .env:       nano /opt/vpnbot/.env"
echo "  2. Перезапусти бота:        docker compose restart"
echo "  3. Настрой 3x-ui:           открой панель в браузере"
echo "  4. Добавь сервер в боте:    /admin -> Добавить сервер"
echo "  5. Настрой тарифы:          /add_plan"
echo ""
echo "  🔑 Где взять токены:"
echo "  • BOT_TOKEN       — https://t.me/BotFather"
echo "  • YOOKASSA        — https://yookassa.ru -> Создать магазин"
echo "  • CRYPTOBOT_TOKEN — https://t.me/CryptoBot -> API"
echo "  • V2RAY_API_URL   — логин в 3x-ui -> Настройки -> API"
echo ""
