# 🌐 VPNBot — Telegram бот для продажи подписок через 3x-ui

Бот продаёт VPN-подписки (VLESS) через Telegram. Пользователь покупает тариф → бот создаёт конфиги на **всех активных серверах** через API 3x-ui → возвращает одну подписочную ссылку для V2RayTun.

---

## 🚀 Быстрый старт

### 1. Установка на VPS (Debian 12)

```bash
# Системные зависимости
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip git curl

# Клонируем бота
git clone https://github.com/your/vpnbot.git
cd vpnbot

# Виртуальное окружение
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Настройка `.env`

```bash
cp .env.example .env
nano .env
```

Обязательные поля:
```
BOT_TOKEN=                       # Токен от @BotFather
ADMIN_IDS=123456789              # Твой Telegram ID (через запятую если несколько)
SUB_DOMAIN=95.123.45.67          # Публичный IP VPS где запущен бот
```

### 3. Установка 3x-ui на каждом сервере

**На каждом VPS, который будет раздавать VPN:**
```bash
bash <(curl -Ls https://raw.githubusercontent.com/alireza0/x-ui/master/install.sh)
```

После установки:
- Зайди в веб-интерфейс: `http://IP_VPS:20537`
- Создай **один** inbound с протоколом **VLESS** (любой порт, например 443)
- Запомни логин/пароль от админки (по умолчанию `admin`/`admin`)

### 4. Добавление серверов в бота

**Способ A — автоимпорт (рекомендуется):**
```
В боте: Админ-панель → 📥 Импорт с 3x-ui → введи IP VPS
```
Бот сам подключится к 3x-ui API (порт 2053), заберёт все inbounds и создаст сервера.

**Способ B — вручную:**
```
/import_inbounds           # Импорт всех inbounds с указанного VPS
/add_server                # Пошаговое добавление сервера
```

### 5. Настройка тарифов

По умолчанию создаются тарифы: `trial` (5 дней), `1month` (30д/299₽), `3months` (90д/699₽), `1year` (365д/1999₽).

Изменить можно командами:
```
/add_plan          # Добавить тариф (пошагово)
/edit_plan [id] [поле] [знач]  # Изменить
/del_plan [id]     # Удалить
```

### 6. Запуск бота

```bash
# Через systemd (рекомендуется)
nano /etc/systemd/system/vpnbot.service
```

```ini
[Unit]
Description=VPNBot
After=network.target

[Service]
User=root
WorkingDirectory=/root/vpnbot
ExecStart=/root/vpnbot/.venv/bin/python app/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now vpnbot
systemctl status vpnbot
```

---

## 🛠 Админ-команды

| Команда | Описание |
|---------|----------|
| `/admin` | Админ-панель (кнопки) |
| `/stats` | Статистика |
| `/traffic` | Нагрузка на сервера |
| `/find [id\|@user]` | Найти пользователя |
| `/ban [id]` | Заблокировать |
| `/unban [id]` | Разблокировать |
| `/give` | Выдать VPN (пошагово) |
| `/extend [id] [дни]` | Продлить подписку |
| `/user_configs [id]` | Конфиги пользователя |
| `/add_plan` | Добавить тариф |
| `/edit_plan [id] [поле] [знач]` | Изменить тариф |
| `/del_plan [id]` | Удалить тариф |
| `/server [id]` | Детали сервера |
| `/server_toggle [id]` | Вкл/выкл сервер |
| `/server_del [id]` | Удалить сервер |
| `/check_server [id]` | Проверить 3x-ui на сервере |
| `/import_inbounds` | Импорт всех inbounds с 3x-ui |
| `/payments` | Последние платежи |
| `/pending_payments` | Оплаченные без активации |
| `/retry_payment [id]` | Повторная активация |
| `/configs` | Все активные конфиги |
| `/backup` | Бэкап БД (только SQLite) |
| `/admin_help` | Cписок команд |

---

## 📡 Архитектура

```
Telegram (пользователь)
        │
        ▼
┌─────────────────┐     HTTP API      ┌──────────────┐
│   VPNBot         │ ──────────────►   │  3x-ui VPS 1  │
│   (Python)       │                   │   (VLESS)     │
│                  │     HTTP API      ├──────────────┤
│  ┌─ Бот ───────┐ │ ──────────────►   │  3x-ui VPS 2  │
│  │ /start      │ │                   │   (VLESS)     │
│  │ /buy        │ │                   ├──────────────┤
│  │ /sub/{token}│ │     HTTP API      │  3x-ui VPS N  │
│  └─────────────┘ │ ──────────────►   │   (VLESS)     │
│                  │                   └──────────────┘
│  ┌─ Подписочный ─┐
│  │ сервер :9090  │ ◄──── V2RayTun (клиент)
│  └──────────────┘
└─────────────────┘
```

- **Бот** — обрабатывает команды, платежи, выдачу подписок
- **Подписочный сервер** (:9090) — отдаёт конфиги по токену пользователя (base64 encoded VLESS links)
- **3x-ui** на каждом VPS — управляет входящими соединениями
- **V2RayTun** — клиент пользователя, импортирует подписку

---

## ⚙️ Конфигурация (`.env`)

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `BOT_TOKEN` | — | Токен Telegram бота |
| `ADMIN_IDS` | — | ID админов (через запятую) |
| `DB_URL` | `sqlite+aiosqlite:///./vpnbot.db` | Строка подключения к БД |
| `SUB_DOMAIN` | `DEFAULT_SERVER_HOST` | Публичный IP/домен бота |
| `V2RAY_USER` | `admin` | Логин 3x-ui |
| `V2RAY_PASS` | `admin` | Пароль 3x-ui |
| `YOOKASSA_SHOP_ID` | — | ID магазина ЮKassa |
| `YOOKASSA_SECRET_KEY` | — | Секретный ключ ЮKassa |
| `CRYPTOBOT_TOKEN` | — | Токен Crypto Bot |
| `TRIAL_DAYS` | `3` | Дней пробного периода |

---

## 💳 Настройка оплаты

### ЮKassa
1. Зарегистрируйся на [yookassa.ru](https://yookassa.ru)
2. Создай магазин, получи `shopId` и `secretKey`
3. Укажи в `.env`:
```ini
YOOKASSA_SHOP_ID=123456
YOOKASSA_SECRET_KEY=test_...
PAYMENT_PROVIDER=yookassa
```

### Crypto Bot
1. Напиши боту [@send](https://t.me/send) → создай API-токен
2. Укажи в `.env`:
```ini
CRYPTOBOT_TOKEN=12345:ABC...
PAYMENT_PROVIDER=cryptobot
```

---

## 🔧 Как это работает (детали)

### Покупка подписки
1. Пользователь нажимает «Купить подписку» → выбирает тариф → оплачивает
2. Бот создаёт подписку в БД
3. Для **каждого активного сервера** бот:
   - Генерирует UUID
   - Создаёт VLESS-ссылку
   - Регистрирует клиента в 3x-ui через API
   - Сохраняет конфиг в БД
4. Пользователю показывается подписочная ссылка: `http://IP:9090/sub/{token}`
5. Пользователь вставляет ссылку в V2RayTun → получает все сервера

### Продление подписки
- При продлении дата сдвигается от текущей даты окончания
- Новые конфиги создаются на **всех активных серверах**
- Просроченные подписки автоматически деактивируются раз в минуту

### Автоимпорт серверов
- `/import_inbounds` — вводишь IP VPS → бот забирает все inbounds из 3x-ui
- Создаёт сервера с правильными портами и протоколами
- Дубликаты (тот же хост+порт) пропускаются

---

## 🔍 Проверка и тесты

```bash
# Проверка синтаксиса всех файлов
python -c "
import ast, os
for root, dirs, files in os.walk('app'):
    for f in files:
        if f.endswith('.py'):
            ast.parse(open(os.path.join(root, f), encoding='utf-8').read())
print('All files OK')
"

# Запуск тестов
python -m pytest tests/ -v
```

---

## 🐛 Возможные проблемы

**Бот не видит сервер / API 3x-ui недоступен**
```
/check_server [id]
```
Проверь: запущен ли 3x-ui, доступен ли порт 2053, правильные ли V2RAY_USER/PASS.

**Подписка работает, но VPN не подключается**
- Проверь inbound в 3x-ui: должен быть VLESS с портом, указанным в боте
- Проверь firewall на VPS: `ufw allow 443` (или твой порт)
- Проверь настройки V2RayTun: протокол VLESS

**Пользователь оплатил, но подписка не активировалась**
```
/pending_payments       # Показать проблемные
/retry_payment [id]     # Повторная активация
```

---

## 📦 Зависимости (requirements.txt)

```
aiogram==3.15.0
sqlalchemy[asyncio]>=2.0
aiosqlite
asyncpg
aiohttp
python-dotenv
redis
pytest
pytest-asyncio
```
