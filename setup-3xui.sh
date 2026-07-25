#!/bin/bash
set -e

# ============================================================
# Настройка 3x-ui + REALITY + SSL-сертификат
# ============================================================

RED='\033[0;31m'
GREEN='\032[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[x]${NC} $1"; exit 1; }

if [ "$EUID" -ne 0 ]; then
    err "Запусти с sudo: sudo bash setup-3xui.sh"
fi

DOMAIN="${1:-}"
if [ -z "$DOMAIN" ]; then
    echo ""
    echo "Использование: sudo bash setup-3xui.sh your-domain.com"
    echo ""
    echo "Сначала купи домен и направь его A-запись на IP этого VPS."
    echo "Пример: sudo bash setup-3xui.sh vpn.moydomain.ru"
    echo ""
    exit 1
fi

log "Настройка 3x-ui для домена: $DOMAIN"

# --- 1. Установка 3x-ui (если ещё не установлена) ---
if ! systemctl is-active --quiet x-ui; then
    log "Установка 3x-ui..."
    bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)
else
    log "3x-ui уже установлена"
fi

# --- 2. Остановка nginx если занят порт 80/443 ---
systemctl stop nginx 2>/dev/null || true

# --- 3. Получение SSL-сертификата ---
log "Получение SSL-сертификата для $DOMAIN..."
certbot certonly --standalone -d "$DOMAIN" --non-interactive --agree-tos -m admin@$DOMAIN || {
    warn "certbot не удался. Пробуем через webroot..."
    systemctl start nginx
    mkdir -p /var/www/html
    certbot certonly --webroot -w /var/www/html -d "$DOMAIN" --non-interactive --agree-tos -m admin@$DOMAIN
}

# --- 4. Копирование сертификатов для 3x-ui ---
log "Установка сертификатов в 3x-ui..."
mkdir -p /etc/x-ui
CERT_DIR="/etc/letsencrypt/live/$DOMAIN"
if [ -f "$CERT_DIR/fullchain.pem" ]; then
    cp "$CERT_DIR/fullchain.pem" /etc/x-ui/server.crt
    cp "$CERT_DIR/privkey.pem" /etc/x-ui/server.key
    chmod 644 /etc/x-ui/server.crt /etc/x-ui/server.key
    log "Сертификаты установлены"
fi

# --- 5. Настройка автообновления сертификатов ---
log "Настройка автообновления SSL..."
cat > /etc/letsencrypt/renewal-hooks/post/restart-xui.sh << 'EOF'
#!/bin/bash
cp /etc/letsencrypt/live/$DOMAIN/fullchain.pem /etc/x-ui/server.crt
cp /etc/letsencrypt/live/$DOMAIN/privkey.pem /etc/x-ui/server.key
chmod 644 /etc/x-ui/server.crt /etc/x-ui/server.key
systemctl restart x-ui
EOF
chmod +x /etc/letsencrypt/renewal-hooks/post/restart-xui.sh

# --- 6. Создание inbounds через API 3x-ui ---
log "Создание inbound-правила в 3x-ui..."

# Пароль по умолчанию, потом смени
XUI_USERNAME="admin"
XUI_PASSWORD="admin"
XUI_BASE="http://localhost:2053"
LOGIN_URL="$XUI_BASE/login"
INBOUND_URL="$XUI_BASE/panel/api/inbounds/add"

# Получаем cookie
COOKIE=$(curl -s -c - "$LOGIN_URL" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$XUI_USERNAME\",\"password\":\"$XUI_PASSWORD\"}" 2>/dev/null | grep -o 'session=[^;]*' | head -1)

if [ -z "$COOKIE" ]; then
    warn "Не удалось залогиниться в 3x-ui. Сделай это вручную: открой http://$(curl -s ifconfig.me):2053"
    warn "Логин: admin | Пароль: admin"
else
    # Создаём VLESS + REALITY inbound
    cat > /tmp/inbound.json << INBEOF
{
    "port": 443,
    "protocol": "vless",
    "settings": "{\"clients\":[],\"decryption\":\"none\",\"fallbacks\":[]}",
    "streamSettings": "{\"network\":\"tcp\",\"security\":\"reality\",\"realitySettings\":{\"dest\":\"www.google.com:443\",\"serverNames\":[\"$DOMAIN\",\"www.google.com\"],\"privateKey\":\"\",\"minClient\":\"\",\"maxClient\":\"\",\"maxTimediff\":0,\"shortIds\":[\"6ba85179e30d4fc2\",\"6ba85179e30d4fc3\"]}}",
    "sniffing": "{\"enabled\":true,\"destOverride\":[\"http\",\"tls\"]}",
    "remark": "VPNBot - VLESS Reality",
    "enable": true
}
INBEOF

    curl -s -b "session=$COOKIE" -X POST "$INBOUND_URL" \
        -H "Content-Type: application/json" \
        -d @/tmp/inbound.json && log "Inbound создан!" || warn "Не удалось создать inbound"
fi

# --- 7. Настройка автообновления сертификатов через cron ---
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet && systemctl restart x-ui") | crontab -

# --- 8. Включаем BBR для скорости ---
log "Включение BBR (ускорение TCP)..."
echo "net.core.default_qdisc=fq" >> /etc/sysctl.conf
echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.conf
sysctl -p

# --- 9. Включаем nginx обратно если он был ---
systemctl start nginx 2>/dev/null || true

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}      3x-ui НАСТРОЕНА!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  🌐 Панель:  https://$DOMAIN:2053"
echo "  🔐 Логин:   admin"
echo "  🔐 Пароль:  admin (СМЕНИ СРАЗУ!)"
echo ""
echo "  📌 Дальнейшие шаги:"
echo "  1. Зайди в панель 3x-ui -> смени пароль"
echo "  2. Зайди в VPNBot -> /admin -> Добавить сервер"
echo "     Введи:"
echo "     - Название: VPS-NL (или любое)"
echo "     - Хост: $DOMAIN"
echo "     - Порт: 443"
echo "     - Протокол: vless"
echo "     - Локация: Netherlands (или твоя)"
echo "  3. Настрой тарифы: /add_plan"
echo "  4. Можно продавать! 🚀"
echo ""
