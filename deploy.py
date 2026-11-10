#!/usr/bin/env python3
"""VPNBot — установка «под ключ».

Примеры:
    python deploy.py                 # .env + развернуть серверы + БД + запустить бота
    python deploy.py --no-run        # всё, кроме запуска бота
    python deploy.py --check         # проверить SSH-доступность серверов
    python deploy.py --sync          # импортировать уже установленные 3x-ui в БД
    python deploy.py --init-env      # только создать/дополнить .env
    python deploy.py --deploy        # только развернуть серверы

Файлы с серверами:
    servers.json  — основной формат (panel + servers)
    servers.txt   — простой формат: ip password [location] [name] [ssh_port] [vpn_port]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
SERVERS_FILE = ROOT / "servers.json"
SERVERS_EXAMPLE = ROOT / "servers.example.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PLACEHOLDER_VALUES = {
    "",
    "your_telegram_bot_token",
    "123456:ABCdef...",
    "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
    "your_usdt_trc20_wallet_address",
    "TWoG8...ABC",
    "1819756249",
    "vpn.example.com",
    "your_bot_username",
}


def _read_env() -> dict[str, str]:
    try:
        from dotenv import dotenv_values

        return {k: (v or "") for k, v in dotenv_values(ENV_FILE).items()}
    except Exception:  # noqa: BLE001
        values: dict[str, str] = {}
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, _, value = line.partition("=")
                    values[key.strip()] = value.strip()
        return values


def _needs_value(current: str | None) -> bool:
    value = (current or "").strip()
    return value in PLACEHOLDER_VALUES or value.startswith("ЗАМЕНИ")


def _ask(label: str, current: str = "", secret: bool = False, required: bool = False,
         non_interactive: bool = False) -> str:
    if not _needs_value(current):
        return current
    if non_interactive or not sys.stdin.isatty():
        return current
    hint = f" [{current}]" if current else ""
    while True:
        prompt = f"{label}{hint}: "
        try:
            value = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return current
        if value:
            return value
        if not required:
            return current
        print("  Это поле обязательно.")


def detect_public_ip(timeout: int = 6) -> str:
    try:
        import urllib.request

        with urllib.request.urlopen("https://api.ipify.org", timeout=timeout) as resp:
            value = resp.read().decode("utf-8").strip()
            if value.count(".") == 3:
                return value
    except Exception:  # noqa: BLE001
        pass
    return ""


def ensure_env(args: argparse.Namespace) -> dict[str, str]:
    """Создаёт .env и заполняет обязательные поля."""
    if not ENV_FILE.exists():
        if ENV_EXAMPLE.exists():
            shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
            print(f"✓ Создан {ENV_FILE.name} из .env.example")
        else:
            ENV_FILE.write_text(
                "BOT_TOKEN=\nADMIN_IDS=\nDB_URL=sqlite+aiosqlite:///./vpnbot.db\n"
                "PAYMENT_PROVIDER=wallet\nWALLET_ADDRESS=\nSUB_PORT=9090\n",
                encoding="utf-8",
            )
            print(f"✓ Создан {ENV_FILE.name}")

    values = _read_env()

    bot_token = args.bot_token or values.get("BOT_TOKEN", "")
    bot_token = _ask("BOT_TOKEN (от @BotFather)", bot_token, secret=True,
                     required=not args.no_run, non_interactive=args.yes)

    admin_ids = args.admin_ids or values.get("ADMIN_IDS", "")
    admin_ids = _ask("ADMIN_IDS (твой Telegram ID, можно несколько через запятую)",
                     admin_ids, required=not args.no_run, non_interactive=args.yes)

    wallet = args.wallet or values.get("WALLET_ADDRESS", "")
    if _needs_value(wallet):
        wallet = _ask("USDT TRC20 кошелёк (Enter — настроить позже)", wallet,
                      non_interactive=args.yes)

    db_url = values.get("DB_URL", "")
    if not db_url:
        db_url = "sqlite+aiosqlite:///./vpnbot.db"

    public_ip = args.public_ip or detect_public_ip()
    default_host = values.get("DEFAULT_SERVER_HOST", "")
    if _needs_value(default_host):
        default_host = public_ip or default_host or "localhost"

    sub_domain = args.sub_domain or values.get("SUB_DOMAIN", "")
    if _needs_value(sub_domain) and public_ip:
        sub_domain = f"http://{public_ip}:9090"

    updates: dict[str, str] = {
        "BOT_TOKEN": bot_token,
        "ADMIN_IDS": admin_ids,
        "DB_URL": db_url,
        "WALLET_ADDRESS": wallet,
        "DEFAULT_SERVER_HOST": default_host,
        "DEFAULT_SERVER_PORT": values.get("DEFAULT_SERVER_PORT") or "443",
        "DEFAULT_PROTOCOL": values.get("DEFAULT_PROTOCOL") or "vless",
        "PAYMENT_PROVIDER": values.get("PAYMENT_PROVIDER") or "wallet",
        "SUB_PORT": values.get("SUB_PORT") or "9090",
    }
    if sub_domain:
        updates["SUB_DOMAIN"] = sub_domain
    if public_ip:
        updates["PUBLIC_IP"] = public_ip

    from app.services.vps_deploy import update_env_file

    update_env_file(updates)
    values.update(updates)
    print(f"✓ {ENV_FILE.name} обновлён")
    if public_ip:
        print(f"  Публичный IP: {public_ip}")
    if sub_domain:
        print(f"  Ссылка подписок: {sub_domain}/sub/<token>")
    return values


def ensure_servers_file() -> None:
    if SERVERS_FILE.exists():
        return
    if SERVERS_EXAMPLE.exists():
        shutil.copyfile(SERVERS_EXAMPLE, SERVERS_FILE)
        print(f"✓ Создан {SERVERS_FILE.name} из {SERVERS_EXAMPLE.name}")
        print("  Впиши IP и root-пароли серверов, затем запусти снова.")
    else:
        SERVERS_FILE.write_text(
            '{"panel": {"username": "admin", "password": "", "port": 2053}, "servers": []}\n',
            encoding="utf-8",
        )
        print(f"✓ Создан пустой {SERVERS_FILE.name}")


async def init_database() -> None:
    from app.database import close_db, init_db

    print("→ Инициализация БД и тарифов...")
    await init_db()
    await close_db()
    print("✓ БД готова")


async def run_deploy(args: argparse.Namespace) -> dict:
    from app.services.vps_deploy import (
        deploy_all, ensure_panel_credentials, is_placeholder_server, load_servers_config,
    )

    panel, servers = load_servers_config(str(SERVERS_FILE) if args.servers else None)
    panel = ensure_panel_credentials(panel, servers)

    real = [s for s in servers if not is_placeholder_server(s)]
    if not servers:
        print("⚠ В servers.json / servers.txt нет серверов — пропускаю развёртывание.")
        return {"total": 0, "success": 0, "failed": 0, "skipped": 0, "results": [], "imported": []}
    if not real:
        print("⚠ Все серверы — placeholder'ы. Впиши реальные IP и пароли в servers.json.")
        return {"total": len(servers), "success": 0, "failed": 0,
                "skipped": len(servers), "results": [], "imported": []}

    print(f"→ Развёртывание {len(real)} сервер(ов)...")
    summary = await deploy_all(servers, panel, progress=lambda text: print(f"  {text}"))
    return summary


async def run_check(args: argparse.Namespace) -> None:
    from app.services.vps_deploy import check_all_servers, load_servers_config

    _panel, servers = load_servers_config(str(SERVERS_FILE) if args.servers else None)
    if not servers:
        print("⚠ Нет серверов в servers.json / servers.txt")
        return
    print("→ Проверка SSH...")
    results = await check_all_servers(servers)
    for item in results:
        name = item.get("name") or item.get("server")
        if item.get("alive"):
            print(f"  ✅ {name} ({item.get('server')}) — ONLINE")
        else:
            print(f"  ❌ {name} ({item.get('server')}) — {item.get('error')}")


async def run_sync(args: argparse.Namespace) -> None:
    from app.services.vps_deploy import load_servers_config, sync_all_to_db

    panel, servers = load_servers_config(str(SERVERS_FILE) if args.servers else None)
    if not servers:
        print("⚠ Нет серверов в servers.json / servers.txt")
        return
    print("→ Синхронизация серверов с БД...")
    summary = await sync_all_to_db(servers, panel)
    for item in summary["results"]:
        icon = "✅" if item.get("success") else "❌"
        detail = item.get("error") or f"server #{item.get('id')}"
        print(f"  {icon} {item.get('server')}: {detail}")
    print(f"✓ Импортировано: {summary['success']}, ошибок: {summary['failed']}")


def print_summary(summary: dict) -> None:
    if not summary:
        return
    print("\n" + "─" * 56)
    print(f"  Серверов: {summary.get('total', 0)} | "
          f"✅ {summary.get('success', 0)} | "
          f"❌ {summary.get('failed', 0)} | "
          f"⏭ {summary.get('skipped', 0)}")
    for item in summary.get("imported", []):
        print(f"  ✅ {item['server']} → server #{item['id']}")
    for result in summary.get("results", []):
        if not result.get("success"):
            server = result.get("server") or {}
            name = server.get("name") or server.get("ip") or "?"
            print(f"  ❌ {name}: {str(result.get('error', ''))[:160]}")
    print("─" * 56)


def start_bot() -> int:
    print("\n→ Запуск Telegram-бота...")
    print("  (Ctrl+C — остановить)\n")
    return subprocess.call([sys.executable, "-m", "app.main"], cwd=str(ROOT))


async def main_async(args: argparse.Namespace) -> int:
    ensure_servers_file()

    try:
        values = ensure_env(args)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Ошибка .env: {exc}")
        return 1

    if args.init_env and not (args.deploy or args.check or args.sync or args.run):
        print("✓ Готово. Заполни servers.json и запусти: python deploy.py")
        return 0

    try:
        await init_database()
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Не удалось инициализировать БД: {exc}")
        print("  Проверь DB_URL в .env и выполни: pip install -r requirements.txt")
        return 1

    summary = None
    try:
        if args.check:
            await run_check(args)
        elif args.sync:
            await run_sync(args)
        elif args.deploy or not args.init_env:
            summary = await run_deploy(args)
            print_summary(summary)
    except RuntimeError as exc:
        print(f"\n❌ {exc}")
        print("  Выполни: pip install -r requirements.txt")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"\n❌ Ошибка развёртывания: {exc}")
        return 1

    if args.run:
        token = values.get("BOT_TOKEN", "")
        if _needs_value(token):
            print("\n❌ BOT_TOKEN не заполнен. Бот не может запуститься.")
            print("  Впиши токен в .env или запусти: python deploy.py --init-env")
            return 1
        if not summary or summary.get("success", 0) == 0:
            print("\n⚠ Ни один сервер не развёрнут. Бот запустится, но продавать VPN пока некуда.")
        return start_bot()

    print("\n✅ Готово.")
    print("   Дальше: python -m app.main   (или python deploy.py, чтобы запустить всё сразу)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="VPNBot: автоустановка 3x-ui и запуск бота «под ключ».",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--deploy", action="store_true", help="Развернуть серверы из servers.json")
    parser.add_argument("--check", action="store_true", help="Проверить SSH-доступность серверов")
    parser.add_argument("--sync", action="store_true", help="Импортировать уже установленные 3x-ui в БД")
    parser.add_argument("--init-env", action="store_true", help="Только создать/дополнить .env")
    parser.add_argument("--no-run", action="store_true", help="Не запускать бота после установки")
    parser.add_argument("--servers", default="", help="Путь к servers.json")
    parser.add_argument("--bot-token", default="", help="BOT_TOKEN для .env")
    parser.add_argument("--admin-ids", default="", help="ADMIN_IDS для .env")
    parser.add_argument("--wallet", default="", help="USDT TRC20 кошелёк")
    parser.add_argument("--sub-domain", default="", help="Публичный адрес подписок, например http://1.2.3.4:9090")
    parser.add_argument("--public-ip", default="", help="Публичный IP этого компьютера")
    parser.add_argument("-y", "--yes", action="store_true", help="Не задавать вопросы (для автоматизации)")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # По умолчанию: развернуть серверы и запустить бота.
    explicit = any([args.deploy, args.check, args.sync, args.init_env])
    if not explicit:
        args.deploy = True
        args.run = not args.no_run
    else:
        args.run = False

    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nОстановлено.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
