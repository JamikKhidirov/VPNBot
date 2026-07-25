# Полный гайд по установке VPN-бота

## Архитектура

```
Твой сервер #1 (Ubuntu) — здесь бот + nginx + сайт подписок
    ├── Telegram Bot (Python)
    ├── Веб-сервер подписок (порт 9090)
    ├── Nginx (порт 443, SSL)
    └── SQLite (БД)

Твой сервер #2 (Ubuntu) — VPN сервер (Нидерланды)
    └── 3x-ui (панель, порт 2053)

Твой сервер #3 (Ubuntu) — VPN сервер (Германия)
    └── 3x-ui (панель, порт 2053)

Твой сервер #4 (Ubuntu) — VPN сервер (Япония)
    └── 3x-ui (панель, порт 2053)
```

---

## Шаг 1. Установка 3x-ui на КАЖДЫЙ VPN-сервер

Заходи на каждый сервер по SSH и выполняй:

```bash
# Установка 3x-ui
bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)
```

После установки:
1. Открой браузер → `http://IP_СЕРВЕРА:2055`
2. Логин по умолчанию: `admin` / `admin`
3. **Сразу смени пароль!**
4. Создай inbound (входящий порт):
   - Нажми «+ добавить inbound»
   - Протокол: `VLESS`
   - Порт: `443` (или любой)
   - Поток: `xtls-rprx-vision`
   - TLS: выключен (Reality включи)
   - Остальное — по умолчанию

Повтори на каждом VPN-сервере.

---

## Шаг 2. Установка бота на основной сервер

Заходи на сервер, где будет жить бот:

```bash
# Установка Docker и Docker Compose
curl -fsSL https://get.docker.com | bash
apt install -y docker-compose-plugin

# Клонирование бота
git clone https://github.com/твой-репозиторий/vpnbot.git /opt/vpnbot
cd /opt/vpnbot

# Настройка
cp .env.example .env
nano .env
```

Заполни `.env`:

```env
BOT_TOKEN=123456:ABCdef...
ADMIN_IDS=123456789

# SQLite (проще всего)
DB_URL=sqlite+aiosqlite:///./data/vpnbot.db

# Твои VPN сервера (3x-ui)
V2RAY_USER=admin
V2RAY_PASS=твой_пароль_от_3xui

# Домен для подписок (купи заранее)
SUB_DOMAIN=https://jvpn.com
SUB_PORT=9090
```

Запуск:

```bash
docker compose up -d
```

---

## Шаг 3. Настройка домена и SSL

```bash
# Установка nginx
apt install -y nginx certbot python3-certbot-nginx

# Создай конфиг
nano /etc/nginx/sites-available/jvpn.com
```

Вставь:

```nginx
server {
    listen 80;
    server_name jvpn.com;

    location / {
        proxy_pass http://127.0.0.1:9090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
# Активируй
ln -s /etc/nginx/sites-available/jvpn.com /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx

# SSL
certbot --nginx -d jvpn.com
```

Готово! Теперь `https://jvpn.com/sub/ТОКЕН` работает.

---

## Шаг 4. Подключение VPN-серверов к боту

В Telegram боте:

```
/admin → Импорт с 3x-ui
→ введи IP первого VPN-сервера
→ бот сам импортирует все inbounds
```

Повтори для каждого сервера.

Или одной командой:

```
/import_inbounds IP_СЕРВЕРА
```

---

## Шаг 5. Брендинг (аватарка, название)

Чтобы в V2RayTun отображалась **твоя аватарка и название**: это настраивается в самом V2RayTun или через subscription-ссылку. Стандартный V2RayTun берёт название из `#VPN-{host}` в ссылке.

Чтобы изменить — открой `app/services/v2ray.py` и замени:

```python
# Строка 54
return f"vless://{uid}@{host}:{port}?{query}#МойВПН-{host}"
```

Или вообще убери `-{host}`:

```python
return f"vless://{uid}@{host}:{port}?{query}#🚀 Мой ВПН"
```

Название сервера в админке тоже можно задать любое — `location` и `name` при импорте.

---

## Команды бота

### Для админа:
| Команда | Что делает |
|---------|-----------|
| `/admin` | Открыть админ-панель |
| `/add_server` | Добавить VPN-сервер руками |
| `/import_inbounds IP` | Импортировать с 3x-ui |
| `/servers` | Список серверов |
| `/stats` | Статистика |
| `/revenue` | Доход |
| `/give TELEGRAM_ID` | Выдать подписку |
| `/extend TELEGRAM_ID ДНИ` | Продлить подписку |
| `/traffic` | Трафик по серверам |
| `/backup` | Бэкап БД |
| `/broadcast` | Рассылка всем |

### Для пользователей:
| Команда | Что делает |
|---------|-----------|
| `/start` | Главное меню |
| `Купить подписку` | Выбор тарифа |
| `Мои конфиги` | Список конфигов |
| `Мой профиль` | Статус подписки |

---

## Как это работает (схема)

```
Пользователь → Бот → Оплата (ЮKassa/CryptoBot)
                → Создание подписки в БД
                → Создание конфига на ВСЕХ VPN-серверах (через API 3x-ui)
                → Показывает ссылку подписки

Пользователь → Вставляет ссылку в V2RayTun
V2RayTun → Запрос на https://jvpn.com/sub/ТОКЕН
         → Получает все конфиги (каждый сервер = отдельная линия)
         → Подключается к самому быстрому
```

---

## Если будут проблемы

1. **3x-ui не отвечает**: проверь `curl http://IP:2053/login`
2. **Конфиги не создаются**: проверь `V2RAY_USER/V2RAY_PASS` в `.env`
3. **Ссылка подписки не открывается**: проверь nginx и `curl http://localhost:9090/sub/ТОКЕН`
4. **V2RayTun не подключается**: проверь что на сервере inbound создан и порт открыт

Тыкай — разберёмся!