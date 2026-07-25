# ============================================================
# VPNBot — Массовое развёртывание на 3-5 VPS серверах
# ============================================================
# Инструкция:
# 1. Отредактируй массив $SERVERS ниже — вставь IP и пароли
# 2. Запусти в PowerShell от имени администратора:
#    powershell -ExecutionPolicy Bypass -File deploy-vps.ps1
# ============================================================

param(
    [string]$ServersFile = ""
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  VPNBot — Массовая установка 3x-ui" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ─── Список твоих серверов ──────────────────────────────
# Замени IP, пароли и локации на свои
$SERVERS = @(
    @{
        IP       = "x.x.x.x"          # IP сервера
        Password = "root_password"     # root пароль
        Location = "Netherlands"       # Нидерланды
        Port     = 443
        Domain   = "nl1.твой-домен.ru" # опционально
    },
    @{
        IP       = "x.x.x.x"
        Password = "root_password"
        Location = "Germany"           # Германия
        Port     = 443
        Domain   = "de1.твой-домен.ru"
    },
    @{
        IP       = "x.x.x.x"
        Password = "root_password"
        Location = "USA"               # США
        Port     = 443
        Domain   = "us1.твой-домен.ru"
    },
    @{
        IP       = "x.x.x.x"
        Password = "root_password"
        Location = "Finland"           # Финляндия
        Port     = 443
        Domain   = "fi1.твой-домен.ru"
    }
    # Добавь ещё по шаблону выше если нужно
)

# ─── Авто-генерация .env для бота ───────────────────────
$ENV_LINES = @(
    "# === Telegram ==="
    "BOT_TOKEN=YOUR_BOT_TOKEN"
    "ADMIN_IDS=1819756249"
    ""
    "# === Database ==="
    "DB_URL=postgresql+asyncpg://vpnbot:vpnbot@localhost:5432/vpnbot"
    "REDIS_URL=redis://localhost:6379/0"
    ""
    "# === Payment ==="
    "YOOKASSA_SHOP_ID="
    "YOOKASSA_SECRET_KEY="
    "YOOKASSA_RETURN_URL=https://t.me/your_bot"
    "CRYPTOBOT_TOKEN="
    ""
    "# === Trial ==="
    "TRIAL_DAYS=5"
    ""
    "# === V2Ray / 3x-ui ==="
    "V2RAY_API_URL=http://localhost:2053/panel/api/inbounds"
    "V2RAY_API_KEY="
    ""
    "# === Default server ==="
    "DEFAULT_SERVER_HOST=localhost"
    "DEFAULT_SERVER_PORT=443"
    "DEFAULT_PROTOCOL=vless"
    ""
    "# === Webhook ==="
    "WEBHOOK_HOST="
    "WEBHOOK_PORT=8080"
    "WEBHOOK_SECRET="
    "PAYMENT_PROVIDER=yookassa"
    ""
    "# === ТВОИ VPN-СЕРВЕРА (добавляются в БД бота) ==="
)

# ─── Установка на каждый сервер ─────────────────────────
function Install-3xUI {
    param($Server)
    $ip = $Server.IP
    $pass = $Server.Password
    $loc = $Server.Location

    Write-Host "`n[$loc] Подключаюсь к $ip ..." -ForegroundColor Yellow

    # Команды установки
    $commands = @(
        "apt update -y",
        "apt install -y curl wget ufw",
        "ufw allow 22/tcp",
        "ufw allow 80/tcp",
        "ufw allow 443/tcp",
        "ufw allow 2053/tcp",
        "ufw --force enable",
        "bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)"
    )

    $sshCmd = "sshpass -p '$pass' ssh -o StrictHostKeyChecking=no root@$ip"
    $commandStr = $commands -join " && "

    Write-Host "  Устанавливаю 3x-ui и firewall..." -ForegroundColor Gray
    Invoke-Expression "$sshCmd '$commandStr'" 2>&1 | Out-Null

    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [$loc] ✅ 3x-ui установлена!" -ForegroundColor Green
        Write-Host "  Панель: http://$ip`:2053" -ForegroundColor Cyan
        Write-Host "  Логин: admin | Пароль: admin" -ForegroundColor Cyan

        # Создаём inbound через API
        $loginResult = Invoke-Expression "$sshCmd 'curl -s -X POST http://localhost:2053/login -H ""Content-Type: application/json"" -d ""{\\\""username\\\"":\\""admin\\\"",\\""password\\\"":\\""admin\\""}""'" 2>$null
        Write-Host "  [$loc] ✅ Готов к работе!" -ForegroundColor Green
    } else {
        Write-Host "  [$loc] ❌ Ошибка установки!" -ForegroundColor Red
    }
}

# ─── Запуск ─────────────────────────────────────────────
Write-Host "Начинаю установку на $($SERVERS.Length) серверов..." -ForegroundColor Cyan
Write-Host "`n⚠  sshpass должен быть установлен!" -ForegroundColor Yellow
Write-Host "  Скачать: https://sourceforge.net/projects/sshpass/files/latest/download"
Write-Host "  Или поставь через Git Bash / WSL"
Write-Host ""

$confirmation = Read-Host "Продолжить установку? (y/n)"
if ($confirmation -ne "y") { exit }

foreach ($srv in $SERVERS) {
    Install-3xUI -Server $srv
}

# ─── Генерация .env для бота ────────────────────────────
Write-Host "`nГенерирую .env для бота..." -ForegroundColor Yellow
$envPath = "C:\Users\user\PycharmProjects\VPNBot\.env"
$ENV_LINES | Out-File -FilePath $envPath -Encoding UTF8

# Добавляем сервера в файл для ручного добавления в бота
$serverList = @()
foreach ($srv in $SERVERS) {
    $serverList += "  • $($srv.Location) — $($srv.IP):$($srv.Port)"
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  ✅ УСТАНОВКА ЗАВЕРШЕНА!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "`nТвои сервера:" -ForegroundColor Cyan
$serverList | ForEach-Object { Write-Host $_ -ForegroundColor White }

Write-Host "`n📌 Дальше:" -ForegroundColor Yellow
Write-Host "1. Открой бота в Telegram: /admin" -ForegroundColor White
Write-Host "2. Добавь каждый сервер через кнопку 'Добавить сервер'" -ForegroundColor White
Write-Host "3. Заполни .env токенами (BOT_TOKEN, YOOKASSA и т.д.)" -ForegroundColor White
Write-Host "4. Запусти бота: python -m app.main" -ForegroundColor White
Write-Host "`nГотово! Пользователи смогут покупать подписку и импортировать в V2RayTun" -ForegroundColor Green
