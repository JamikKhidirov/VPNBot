# Полный гайд по установке VPNBot

> Короткая версия: заполни `servers.json` → `python deploy.py` → продавай.
> Этот гайд — для тех, кто хочет понимать, что происходит внутри, и настроить всё «по-взрослому».

---

## 1. Что понадобится

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| Машина для бота | Windows / Linux / macOS, Python 3.11+ | отдельный VPS с Ubuntu 24.04 |
| VPN-серверы | 1 × Ubuntu 22.04/24.04, root | 2–5 серверов в разных странах |
| Telegram | токен от [@BotFather](https://t.me/BotFather) | — |
| Оплата | USDT TRC20 кошелёк | ЮKassa или Crypto Bot |
| Домен | не обязателен | для HTTPS-подписок |

> Бот **не обязан** жить на VPN-сервере. Он может работать на вашем компьютере и управлять удалёнными VPS по SSH.

---

## 2. Как устроено

```text
Компьютер / VPS с ботом (Ubuntu или Windows)
├── Telegram-бот (aiogram)
├── Подписочный сервер :9090  → /sub/<token>
├── SQLite (по умолчанию) или PostgreSQL
└── deploy.py → SSH → VPN-серверы

VPN-сервер #1 (Нидерланды)          VPN-сервер #2 (Германия)
├── 3x-ui (панель :2053)             ├── 3x-ui (панель :2053)
├── VLESS Reality (:443)             ├── VLESS Reality (:443)
├── Xray / systemd                   ├── Xray / systemd
└── UFW + BBR                        └── UFW + BBR
```

Пользователь покупает подписку → бот создаёт клиента **на всех активных серверах** → отдаёт **одну** ссылку-подписку. Клиент (V2RayTun / v2rayNG / Hiddify) сам получает список всех локаций.

---

## 3. Установка «под ключ»

### 3.1. Скачать проект

```bash
git clone https://github.com/JamikKhidirov/VPNBot.git
cd VPNBot
python -m pip install -r requirements.txt
```

Windows:

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3.2. Указать серверы

```bash
cp servers.example.json servers.json
```

Заполни `servers.json`:

```json
{
    "panel": {
        "username": "admin",
        "password": "",
        "port": 2053
    },
    "servers": [
        {
            "ip": "1.2.3.4",
            "password": "root-пароль",
            "location": "Netherlands",
            "name": "Amsterdam NL-1",
            "ssh_port": 22,
            "vpn_port": 443
        }
    ]
}
```

Поля:

| Поле | Обязательно | Описание |
|------|:-----------:|----------|
| `ip` | ✅ | публичный IP VPN-сервера |
| `password` | ✅ | root-пароль по SSH |
| `location` | ➖ | страна/город для красивой метки |
| `name` | ➖ | название сервера |
| `ssh_port` | ➖ | по умолчанию `22` |
| `vpn_port` | ➖ | порт VLESS, по умолчанию `443` |
| `protocol` | ➖ | `vless` (по умолчанию) |

Альтернатива — `servers.txt`, по одному серверу в строке:

```text
# ip        password      location      name             ssh  vpn  panel
1.2.3.4     root-пароль   Netherlands   Amsterdam-NL-1   22   443  2053
```

`servers.txt` дополняет и переопределяет записи из `servers.json`.

### 3.3. Одна команда

```bash
python deploy.py
```

Что произойдёт:

1. создаст `.env` из `.env.example`;
2. спросит `BOT_TOKEN` и `ADMIN_IDS`;
3. сгенерирует пароль панели 3x-ui (если пустой) и запишет его в `.env` + `servers.json`;
4. инициализирует SQLite и тарифы;
5. по SSH на каждый сервер:
   - поставит `curl`, `ufw`, `jq`, `openssl`;
   - настроит firewall (SSH, VPN, панель, 80/443);
   - включит BBR;
   - установит 3x-ui;
   - задаст логин/пароль/порт панели;
6. создаст **VLESS Reality** inbound и ключи X25519;
7. добавит сервер в базу бота;
8. запустит Telegram-бота и подписочный сервер.

В конце увидишь:

```text
  Серверов: 2 | ✅ 2 | ❌ 0 | ⏭ 0
  ✅ Amsterdam NL-1 → server #1
  ✅ Frankfurt DE-1 → server #2
```

### 3.4. Если не хочешь запускать бота сразу

```bash
python deploy.py --no-run
python -m app.main
```

---

## 4. Проверка и обслуживание

```bash
python deploy.py --check      # SSH-доступность всех серверов
python deploy.py --sync       # импорт существующих 3x-ui в БД
python deploy.py --init-env   # только .env
python deploy.py --deploy     # только развёртывание
```

В Telegram:

```text
/admin → 🌐 VPS сервера → 🔄 Проверить все
/admin → 📊 Статистика
/online
/server_load
```

### Обновление проекта

```bash
git pull
python -m pip install -r requirements.txt
python deploy.py --sync --no-run
```

---

## 5. Настройка оплаты

### Вариант A. USDT TRC20 (проще всего)

```ini
PAYMENT_PROVIDER=wallet
WALLET_ADDRESS=TWoG8...твой_кошелёк
WALLET_CURRENCY=USDT (TRC20)
```

Пользователь переводит USDT → нажимает «Проверить оплату» → админ подтверждает:

```text
/pending_wallet
/confirm_payment <id>
```

### Вариант B. ЮKassa (карты РФ, СБП)

```ini
PAYMENT_PROVIDER=yookassa
YOOKASSA_SHOP_ID=123456
YOOKASSA_SECRET_KEY=live_...
YOOKASSA_RETURN_URL=https://t.me/your_bot
```

### Вариант C. Crypto Bot (USDT через Telegram)

```ini
PAYMENT_PROVIDER=cryptobot
CRYPTOBOT_TOKEN=12345:ABC...
```

---

## 6. Подписки и домен

По умолчанию ссылка выглядит так:

```text
http://IP_БОТА:9090/sub/<token>
```

Если бот работает на VPS, открой порт:

```bash
ufw allow 9090/tcp
```

Хочешь HTTPS и красивый домен — поставь Nginx и Certbot:

```bash
apt install -y nginx certbot python3-certbot-nginx
nano /etc/nginx/sites-available/vpnbot
```

```nginx
server {
    listen 80;
    server_name vpn.example.com;

    location / {
        proxy_pass http://127.0.0.1:9090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/vpnbot /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d vpn.example.com
```

И пропиши в `.env`:

```ini
SUB_DOMAIN=https://vpn.example.com
SUB_PORT=9090
```

---

## 7. Брендинг в V2RayTun

Название сервера берётся из `name` / `location` в `servers.json` и попадает в ссылку как метка. Чтобы изменить стиль меток, отредактируй `_fragment()` в `app/services/v2ray.py`.

Название бота, описание и аватар меняются в [@BotFather](https://t.me/BotFather).

---

## 8. Безопасность

1. `servers.json`, `servers.txt`, `.env`, `vpnbot.db` уже в `.gitignore`.
2. Пароль 3x-ui генерируется автоматически. Никому его не показывай.
3. После установки закрой панель от внешнего мира:

```bash
ufw delete allow 2053/tcp
ufw allow from ТВОЙ_IP to any port 2053 proto tcp
```

4. Смени root-пароли на SSH-ключи:

```bash
ssh-copy-id root@IP
# затем отключи PasswordAuthentication в /etc/ssh/sshd_config
```

5. Делай бэкапы: `/backup` в боте или

```bash
cp vpnbot.db "vpnbot_backup_$(date +%F).db"
```

---

## 9. Диагностика

| Симптом | Проверка |
|---------|----------|
| `asyncssh не установлен` | `pip install -r requirements.txt` |
| `Permission denied (publickey,password)` | неверный root-пароль или порт SSH |
| `install script exit` | сервер не Ubuntu / нет интернета / нет root |
| Панель не открывается | `ufw status`, `systemctl status x-ui`, `curl http://IP:2053/login` |
| Inbound не создаётся | `journalctl -u x-ui -n 100 --no-pager` |
| Ссылка подписки пустая | нет активных серверов или конфигов; `/sync_servers` |
| V2RayTun не подключается | порт VPN закрыт firewall или inbound не Reality |
| Бот молчит | `BOT_TOKEN`, `BOT_PROXY`, логи `python -m app.main` |
| Платёж не активировал подписку | `/retry_payment <id>` |

### Логи

```bash
# бот
python -m app.main

# 3x-ui на VPN-сервере
journalctl -u x-ui -f

# конфиг Xray
cat /usr/local/x-ui/bin/config.json
```

---

## 10. Запуск в Docker (опционально)

```bash
cp .env.example .env
# заполни BOT_TOKEN, ADMIN_IDS, WALLET_ADDRESS
touch vpnbot.db
docker compose up -d --build
docker compose logs -f bot
```

Сервисы:

- `bot` — сам бот + подписки (`:9090`);
- `postgres` — профиль `postgres`;
- `redis` — профиль `redis`.

```bash
docker compose --profile postgres --profile redis up -d
```

---

## 11. Полезные команды

```bash
python deploy.py                # всё сразу
python deploy.py --no-run       # установка без запуска
python deploy.py --check        # SSH-проверка
python deploy.py --sync         # импорт серверов в БД
python -m pytest tests/ -q      # тесты
```

```text
/admin          админ-панель
/give <id>      выдать VPN
/extend <id> <дни>
/stats          статистика
/online         онлайн
/server_load    нагрузка
/backup         бэкап БД
/deploy_all     развернуть все серверы
/sync_servers   импорт из 3x-ui
```

---

Готово. Если что-то не работает — сначала `python deploy.py --check`, потом смотри таблицу выше.
