"""Автоматическое развёртывание 3x-ui и импорт VPN-серверов.

Один файл `servers.json` (или `servers.txt`) → одна команда `python deploy.py`
→ установленный 3x-ui, настроенный firewall, VLESS Reality inbound и сервер в БД бота.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import logging
import os
import re
import secrets
import shlex
import string
from typing import Any, Callable

try:  # asyncssh нужен только для реального SSH-развёртывания.
    import asyncssh
except ImportError:  # pragma: no cover - локальная среда без asyncssh
    asyncssh = None

logger = logging.getLogger(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVERS_FILE = os.path.join(ROOT_DIR, "servers.json")
SERVERS_TXT = os.path.join(ROOT_DIR, "servers.txt")
ENV_FILE = os.path.join(ROOT_DIR, ".env")

DEFAULT_PANEL: dict[str, Any] = {
    "username": "admin",
    "password": "",
    "port": 2053,
    "scheme": "http",
}

PLACEHOLDER_HOSTS = {
    "x.x.x.x",
    "0.0.0.0",
    "127.0.0.1",
    "localhost",
    "example.com",
    "your_server_ip",
    "your-domain.com",
}

DEFAULT_REALITY_SNI = "www.microsoft.com"


# ────────────────────────────────────────────────────────────
#  Файлы конфигурации
# ────────────────────────────────────────────────────────────

def _generate_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on", "да")


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_servers_txt(path: str = SERVERS_TXT) -> list[dict[str, Any]]:
    """Формат строки: ip password [location] [name] [ssh_port] [vpn_port] [panel_port]."""
    servers: list[dict[str, Any]] = []
    if not os.path.exists(path):
        return servers

    with open(path, encoding="utf-8-sig") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                parts = shlex.split(line, comments=True)
            except ValueError:
                parts = line.split()
            if len(parts) < 2:
                continue
            servers.append({
                "ip": parts[0],
                "password": parts[1],
                "location": parts[2] if len(parts) > 2 else "",
                "name": parts[3] if len(parts) > 3 else "",
                "ssh_port": _parse_int(parts[4], 22) if len(parts) > 4 else 22,
                "vpn_port": _parse_int(parts[5], 443) if len(parts) > 5 else 443,
                "panel_port": _parse_int(parts[6], 0) if len(parts) > 6 else 0,
            })
    return servers


def _normalize_server(raw: dict[str, Any], panel: dict[str, Any], index: int = 0) -> dict[str, Any]:
    ip = str(
        raw.get("ip")
        or raw.get("host")
        or raw.get("address")
        or raw.get("server")
        or ""
    ).strip()

    password = str(
        raw.get("password")
        or raw.get("root_password")
        or raw.get("pass")
        or raw.get("ssh_password")
        or ""
    ).strip()

    name = str(raw.get("name") or raw.get("title") or "").strip() or f"VPS {ip or index + 1}"
    location = str(raw.get("location") or raw.get("country") or raw.get("city") or "").strip()

    return {
        **raw,
        "ip": ip,
        "password": password,
        "name": name,
        "location": location,
        "ssh_port": _parse_int(raw.get("ssh_port") or raw.get("port"), 22),
        "vpn_port": _parse_int(raw.get("vpn_port") or raw.get("xray_port"), 443),
        "panel_port": _parse_int(raw.get("panel_port"), _parse_int(panel.get("port"), 2053)),
        "panel_user": str(raw.get("panel_user") or panel.get("username") or "admin"),
        "panel_pass": str(raw.get("panel_pass") or raw.get("panel_password") or panel.get("password") or ""),
        "protocol": str(raw.get("protocol") or "vless"),
        "domain": str(raw.get("domain") or ""),
        "deployed": _parse_bool(raw.get("deployed", False)),
    }


def load_servers_config(path: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Загружает panel + servers из servers.json и/или servers.txt.

    Поддерживаются оба формата:
      * {"panel": {...}, "servers": [...]}
      * просто список серверов (старый формат)
    """
    panel = dict(DEFAULT_PANEL)
    raw_servers: list[dict[str, Any]] = []
    configured_file = path or os.getenv("SERVERS_FILE") or SERVERS_FILE

    if os.path.exists(configured_file):
        try:
            with open(configured_file, encoding="utf-8-sig") as f:
                data = json.load(f)
            if isinstance(data, list):
                raw_servers = data
            elif isinstance(data, dict):
                panel.update(data.get("panel") or {})
                raw_servers = data.get("servers") or data.get("vps") or []
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Не удалось прочитать %s: %s", configured_file, exc)

    # servers.txt — простой формат «одна строка = один сервер».
    extra = _parse_servers_txt()
    if extra:
        by_ip = {str(s.get("ip") or ""): s for s in raw_servers}
        for server in extra:
            by_ip[str(server.get("ip") or "")] = server
        raw_servers = [s for s in by_ip.values() if s.get("ip")]

    panel["username"] = str(panel.get("username") or "admin")
    panel["password"] = str(panel.get("password") or "")
    panel["port"] = _parse_int(panel.get("port"), 2053)
    panel["scheme"] = str(panel.get("scheme") or "http")

    servers = [
        _normalize_server(s, panel, i)
        for i, s in enumerate(raw_servers)
        if isinstance(s, dict)
    ]
    return panel, servers


def save_servers_config(panel: dict[str, Any], servers: list[dict[str, Any]], path: str | None = None) -> None:
    target = path or os.getenv("SERVERS_FILE") or SERVERS_FILE
    payload = {
        "panel": {
            "username": panel.get("username", "admin"),
            "password": panel.get("password", ""),
            "port": _parse_int(panel.get("port"), 2053),
            "scheme": panel.get("scheme", "http"),
        },
        "servers": servers,
    }
    with open(target, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)
        f.write("\n")


def load_vps_servers() -> list[dict[str, Any]]:
    """Совместимость со старым API: только список серверов."""
    _panel, servers = load_servers_config()
    return servers


def save_vps_servers(servers: list[dict[str, Any]]) -> None:
    """Совместимость со старым API: сохраняет список, не теряя panel."""
    panel, _ = load_servers_config()
    save_servers_config(panel, servers)


# ────────────────────────────────────────────────────────────
#  .env
# ────────────────────────────────────────────────────────────

def update_env_file(updates: dict[str, str], path: str = ENV_FILE) -> None:
    """Аккуратно обновляет ключи в .env, не удаляя комментарии и прочие строки."""
    lines: list[str] = []
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()

    found: set[str] = set()
    result: list[str] = []
    for line in lines:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if match and match.group(1) in updates:
            key = match.group(1)
            result.append(f"{key}={updates[key]}")
            found.add(key)
        else:
            result.append(line)

    for key, value in updates.items():
        if key not in found:
            result.append(f"{key}={value}")

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(result).rstrip() + "\n")


def ensure_panel_credentials(panel: dict[str, Any] | None = None,
                             servers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Гарантирует, что у панели есть нормальный пароль, и синхронизирует его с .env."""
    if panel is None or servers is None:
        panel, loaded_servers = load_servers_config()
        if servers is None:
            servers = loaded_servers

    changed = False
    if not panel.get("username"):
        panel["username"] = "admin"
        changed = True
    if not panel.get("password") or str(panel["password"]).lower() in {"admin", "password", "root_password", "changeme"}:
        panel["password"] = _generate_password(24)
        changed = True
    if not (1 <= _parse_int(panel.get("port"), 0) <= 65535):
        panel["port"] = 2053
        changed = True
    if not panel.get("scheme"):
        panel["scheme"] = "http"
        changed = True

    if changed:
        for server in servers:
            server["panel_user"] = panel["username"]
            server["panel_pass"] = panel["password"]
            server["panel_port"] = _parse_int(panel.get("port"), 2053)
        save_servers_config(panel, servers)

    update_env_file({
        "V2RAY_USER": str(panel["username"]),
        "V2RAY_PASS": str(panel["password"]),
        "V2RAY_PANEL_PORT": str(_parse_int(panel.get("port"), 2053)),
        "V2RAY_PANEL_SCHEME": str(panel.get("scheme", "http")),
    })
    return panel


# ────────────────────────────────────────────────────────────
#  Валидация и SSH
# ────────────────────────────────────────────────────────────

def is_placeholder_server(server: dict[str, Any]) -> bool:
    host = str(server.get("ip") or "").strip().lower()
    if not host or host in PLACEHOLDER_HOSTS:
        return True
    if host.startswith("x.") or host.endswith(".example.com"):
        return True
    if not str(server.get("password") or "").strip():
        return True
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        return not bool(re.match(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$", host))


def _require_asyncssh() -> None:
    if asyncssh is None:
        raise RuntimeError(
            "asyncssh не установлен. Выполни: pip install -r requirements.txt"
        )


async def _ssh_connect(server: dict[str, Any], timeout: int = 20):
    _require_asyncssh()
    return await asyncssh.connect(
        host=server["ip"],
        port=_parse_int(server.get("ssh_port"), 22),
        username=str(server.get("ssh_user") or "root"),
        password=server["password"],
        known_hosts=None,
        connect_timeout=timeout,
        login_timeout=timeout,
    )


async def check_server_ssh(ip: str, password: str, port: int = 22) -> dict[str, Any]:
    result: dict[str, Any] = {"alive": False, "error": ""}
    try:
        _require_asyncssh()
        async with asyncssh.connect(
            host=ip,
            port=port,
            username="root",
            password=password,
            known_hosts=None,
            connect_timeout=15,
            login_timeout=15,
        ) as conn:
            resp = await conn.run("uname -a && cat /etc/os-release | head -3", timeout=15, check=False)
            if resp.exit_status == 0:
                result["alive"] = True
                result["os"] = (resp.stdout or "").strip()
            else:
                result["error"] = (resp.stderr or "SSH command failed").strip()
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    return result


# ────────────────────────────────────────────────────────────
#  Установка 3x-ui
# ────────────────────────────────────────────────────────────

def _install_script(server: dict[str, Any], panel: dict[str, Any]) -> str:
    q = shlex.quote
    ssh_port = _parse_int(server.get("ssh_port"), 22)
    vpn_port = _parse_int(server.get("vpn_port"), 443)
    panel_port = _parse_int(server.get("panel_port") or panel.get("port"), 2053)
    panel_user = str(server.get("panel_user") or panel.get("username") or "admin")
    panel_pass = str(server.get("panel_pass") or panel.get("password") or "")
    panel_path = str(panel.get("path") or "").strip("/")

    return f"""set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive
export XUI_USERNAME={q(panel_user)}
export XUI_PASSWORD={q(panel_pass)}
export XUI_PORT={q(str(panel_port))}
export XUI_DB_TYPE=sqlite

echo "=== [1/6] apt update ==="
apt-get update -y
apt-get install -y curl wget ca-certificates ufw openssl jq

echo "=== [2/6] firewall ==="
ufw allow {ssh_port}/tcp || true
ufw allow {vpn_port}/tcp || true
ufw allow {vpn_port}/udp || true
ufw allow {panel_port}/tcp || true
ufw allow 80/tcp || true
ufw allow 443/tcp || true
ufw --force enable || true

echo "=== [3/6] BBR ==="
grep -q '^net.core.default_qdisc=fq' /etc/sysctl.conf 2>/dev/null || echo 'net.core.default_qdisc=fq' >> /etc/sysctl.conf
grep -q '^net.ipv4.tcp_congestion_control=bbr' /etc/sysctl.conf 2>/dev/null || echo 'net.ipv4.tcp_congestion_control=bbr' >> /etc/sysctl.conf
sysctl -p >/dev/null 2>&1 || true

echo "=== [4/6] 3x-ui install ==="
if ! command -v x-ui >/dev/null 2>&1 && [ ! -x /usr/local/x-ui/x-ui ]; then
  bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh) </dev/null || true
fi

XUI_BIN="$(command -v x-ui || true)"
if [ -z "$XUI_BIN" ] && [ -x /usr/local/x-ui/x-ui ]; then
  XUI_BIN=/usr/local/x-ui/x-ui
fi
if [ -n "$XUI_BIN" ] && [ -x "$XUI_BIN" ]; then
  "$XUI_BIN" setting -username {q(panel_user)} -password {q(panel_pass)} -port {q(str(panel_port))} || true
  "$XUI_BIN" setting -listenIP 0.0.0.0 || true
  {f'"$XUI_BIN" setting -webBasePath {q("/" + panel_path if panel_path else "/")} || true' if panel_path else ''}
fi

systemctl enable x-ui >/dev/null 2>&1 || true
systemctl restart x-ui >/dev/null 2>&1 || true

echo "=== [5/6] wait panel ==="
PANEL_OK=0
for i in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{panel_port}/login || true)
  if [ "$code" = "200" ]; then
    PANEL_OK=1
    echo "PANEL_OK"
    break
  fi
  sleep 2
done

echo "=== [6/6] status ==="
systemctl --no-pager --full status x-ui | head -20 || true
curl -s -o /dev/null -w 'PANEL_HTTP=%{{http_code}}\\n' http://127.0.0.1:{panel_port}/login || true
if [ "$PANEL_OK" != "1" ]; then
  echo "PANEL_NOT_READY" >&2
  exit 3
fi
"""


async def install_3xui_on_server(ip: str, password: str, port: int = 22,
                                 panel: dict[str, Any] | None = None,
                                 server: dict[str, Any] | None = None) -> dict[str, Any]:
    """Совместимая обёртка: устанавливает 3x-ui на один сервер."""
    if panel is None:
        panel, loaded_servers = load_servers_config()
    else:
        loaded_servers = [server] if server else []
    panel = ensure_panel_credentials(panel, loaded_servers)
    target = server or {
        "ip": ip,
        "password": password,
        "ssh_port": port,
        "name": f"VPS {ip}",
        "location": "",
        "vpn_port": 443,
        "panel_port": _parse_int(panel.get("port"), 2053),
        "panel_user": panel["username"],
        "panel_pass": panel["password"],
    }
    result: dict[str, Any] = {"success": False, "output": "", "error": ""}
    try:
        _require_asyncssh()
        async with await _ssh_connect(target) as conn:
            resp = await conn.run(
                "bash -s",
                input=_install_script(target, panel),
                timeout=900,
                check=False,
            )
            result["output"] = (resp.stdout or "")[-12000:]
            if resp.exit_status != 0:
                result["error"] = (resp.stderr or f"install script exit {resp.exit_status}")[-4000:]
                return result
            result["success"] = True
            result["panel"] = {
                "url": f"http://{ip}:{_parse_int(panel.get('port'), 2053)}",
                "username": panel["username"],
                "password": panel["password"],
            }
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    return result


# ────────────────────────────────────────────────────────────
#  3x-ui API
# ────────────────────────────────────────────────────────────

def _panel_for_server(server: dict[str, Any], panel: dict[str, Any] | None = None) -> dict[str, Any]:
    if panel is None:
        panel, _ = load_servers_config()
    return {
        "username": str(server.get("panel_user") or panel.get("username") or "admin"),
        "password": str(server.get("panel_pass") or panel.get("password") or ""),
        "port": _parse_int(server.get("panel_port") or panel.get("port"), 2053),
        "scheme": str(panel.get("scheme") or "http"),
        "path": str(panel.get("path") or "").strip("/"),
    }


async def _panel_request(host: str, panel: dict[str, Any], method: str, path: str,
                         data: dict[str, Any] | None = None, timeout: int = 25) -> dict[str, Any] | None:
    import aiohttp

    scheme = panel.get("scheme", "http")
    base_path = f"/{panel['path'].strip('/')}" if panel.get("path") else ""
    base = f"{scheme}://{host}:{_parse_int(panel.get('port'), 2053)}{base_path}"

    connector = aiohttp.TCPConnector(ssl=False)
    jar = aiohttp.CookieJar(unsafe=True)
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    headers = {"Accept": "application/json", "User-Agent": "VPNBot/2.0"}

    try:
        async with aiohttp.ClientSession(connector=connector, cookie_jar=jar, timeout=client_timeout) as session:
            async with session.post(
                f"{base}/login",
                json={"username": panel["username"], "password": panel["password"]},
                headers=headers,
            ) as login_resp:
                if login_resp.status != 200:
                    logger.warning("3x-ui login HTTP %s on %s", login_resp.status, host)
                    return None
                try:
                    login_data = await login_resp.json(content_type=None)
                except Exception:  # noqa: BLE001
                    login_data = {}
                if isinstance(login_data, dict) and login_data.get("success") is False:
                    logger.warning("3x-ui login rejected on %s: %s", host, login_data.get("msg"))
                    return None

            async with session.request(method, f"{base}{path}", json=data, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning("3x-ui API %s %s HTTP %s on %s", method, path, resp.status, host)
                    return None
                try:
                    payload = await resp.json(content_type=None)
                except Exception:  # noqa: BLE001
                    return None
                return payload if isinstance(payload, dict) else {"obj": payload}
    except Exception as exc:  # noqa: BLE001
        logger.warning("3x-ui API error on %s: %s", host, exc)
        return None


async def _list_inbounds(host: str, panel: dict[str, Any]) -> list[dict[str, Any]]:
    data = await _panel_request(host, panel, "GET", "/panel/api/inbounds/list")
    if not data:
        return []
    obj = data.get("obj")
    return obj if isinstance(obj, list) else []


def _json_field(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _decode_b64(value: str) -> bytes | None:
    value = (value or "").strip()
    if not value:
        return None
    padding = "=" * (-len(value) % 4)
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            return decoder(value + padding)
        except Exception:  # noqa: BLE001
            continue
    return None


def derive_public_key(private_key: str) -> str:
    """X25519: вычисляет публичный ключ REALITY из приватного."""
    raw = _decode_b64(private_key)
    if not raw or len(raw) != 32:
        return ""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        private = X25519PrivateKey.from_private_bytes(raw)
        public_raw = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.urlsafe_b64encode(public_raw).decode().rstrip("=")
    except Exception:  # noqa: BLE001
        return ""


def enrich_inbound(inbound: dict[str, Any], host: str, panel: dict[str, Any]) -> dict[str, Any]:
    stream = _json_field(inbound.get("streamSettings"))
    reality = _json_field(stream.get("realitySettings"))
    tls = _json_field(stream.get("tlsSettings"))
    network = str(stream.get("network") or "tcp")
    security = str(stream.get("security") or "none")

    server_names = reality.get("serverNames") or []
    sni = ""
    if isinstance(server_names, list) and server_names:
        sni = str(server_names[0])
    if not sni:
        sni = str(reality.get("dest") or "").split(":")[0]
    if not sni:
        sni = str(tls.get("serverName") or "")
    if not sni:
        sni = host

    private_key = str(reality.get("privateKey") or "")
    public_key = str(reality.get("publicKey") or "")
    if not public_key:
        public_key = str(_json_field(reality.get("settings")).get("publicKey") or "")
    if not public_key and private_key:
        public_key = derive_public_key(private_key)

    short_ids = reality.get("shortIds") or []
    short_id = str(short_ids[0]) if isinstance(short_ids, list) and short_ids else ""

    ws_settings = stream.get("wsSettings")
    grpc_settings = stream.get("grpcSettings")
    ws_path = ws_settings.get("path") if isinstance(ws_settings, dict) else ""
    grpc_service = grpc_settings.get("serviceName") if isinstance(grpc_settings, dict) else ""

    return {
        "inbound_id": inbound.get("id"),
        "remark": inbound.get("remark") or "",
        "host": host,
        "port": _parse_int(inbound.get("port"), 443),
        "protocol": str(inbound.get("protocol") or "vless").lower(),
        "security": security,
        "network": network,
        "sni": sni,
        "public_key": public_key,
        "short_id": short_id,
        "short_ids": short_ids if isinstance(short_ids, list) else [short_id] if short_id else [],
        "flow": "xtls-rprx-vision" if security == "reality" and network in ("tcp", "raw") else "",
        "fingerprint": "chrome",
        "dest": reality.get("dest") or "",
        "path": ws_path or "",
        "grpc_service": grpc_service or "",
        "panel_port": _parse_int(panel.get("port"), 2053),
        "panel_user": panel.get("username"),
        "panel_scheme": panel.get("scheme", "http"),
    }


async def _get_x25519(server: dict[str, Any], panel: dict[str, Any]) -> dict[str, str] | None:
    data = await _panel_request(server["ip"], panel, "GET", "/panel/api/server/getNewX25519Cert")
    if data:
        obj = data.get("obj") or {}
        private_key = str(obj.get("privateKey") or "")
        public_key = str(obj.get("publicKey") or "")
        if private_key:
            if not public_key:
                public_key = derive_public_key(private_key)
            return {"privateKey": private_key, "publicKey": public_key}

    # Fallback: xray x25519 прямо на сервере.
    try:
        async with await _ssh_connect(server) as conn:
            resp = await conn.run(
                "XRAY_BIN=$(command -v xray || true); "
                "if [ -z \"$XRAY_BIN\" ]; then XRAY_BIN=$(find /usr/local/x-ui/bin -maxdepth 1 -type f -name 'xray*' 2>/dev/null | head -1); fi; "
                "\"$XRAY_BIN\" x25519 2>/dev/null || true",
                timeout=20,
                check=False,
            )
            text = resp.stdout or ""
            private_key = ""
            public_key = ""
            for line in text.splitlines():
                low = line.lower()
                if "private" in low and ":" in line:
                    private_key = line.split(":", 1)[1].strip()
                elif "public" in low and ":" in line:
                    public_key = line.split(":", 1)[1].strip()
            if private_key:
                return {
                    "privateKey": private_key,
                    "publicKey": public_key or derive_public_key(private_key),
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning("x25519 fallback failed on %s: %s", server["ip"], exc)
    return None


def _inbound_payload(server: dict[str, Any], keys: dict[str, str], short_id: str, sni: str) -> dict[str, Any]:
    vpn_port = _parse_int(server.get("vpn_port"), 443)
    remark = f"VPNBot | {server.get('name') or server['ip']} | VLESS Reality"

    stream = {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
            "show": False,
            "xver": 0,
            "dest": f"{sni}:443",
            "serverNames": [sni],
            "privateKey": keys["privateKey"],
            "minClient": "",
            "maxClient": "",
            "maxTimediff": 0,
            "shortIds": [short_id],
            "settings": {
                "publicKey": keys["publicKey"],
                "fingerprint": "chrome",
                "serverName": "",
                "spiderX": "/",
            },
        },
    }

    return {
        "up": 0,
        "down": 0,
        "total": 0,
        "remark": remark,
        "enable": True,
        "expiryTime": 0,
        "listen": "",
        "port": vpn_port,
        "protocol": "vless",
        "settings": json.dumps(
            {"clients": [], "decryption": "none", "fallbacks": []},
            ensure_ascii=False,
        ),
        "streamSettings": json.dumps(stream, ensure_ascii=False),
        "sniffing": json.dumps(
            {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": True},
            ensure_ascii=False,
        ),
        "allocate": json.dumps(
            {"strategy": "always", "refresh": 5, "concurrency": 3},
            ensure_ascii=False,
        ),
    }


async def ensure_inbound(server: dict[str, Any], panel: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Создаёт (или возвращает существующий) VLESS Reality inbound."""
    panel = _panel_for_server(server, panel)
    vpn_port = _parse_int(server.get("vpn_port"), 443)

    inbounds = await _list_inbounds(server["ip"], panel)
    for inbound in inbounds:
        if _parse_int(inbound.get("port"), 0) != vpn_port:
            continue
        if str(inbound.get("protocol") or "").lower() not in ("vless", "vmess"):
            continue
        logger.info("[%s] inbound уже существует на порту %s", server["ip"], vpn_port)
        return enrich_inbound(inbound, server["ip"], panel)

    keys = await _get_x25519(server, panel)
    if not keys or not keys.get("privateKey"):
        logger.error("[%s] не удалось получить X25519 ключи", server["ip"])
        return None

    short_id = secrets.token_hex(4)
    sni = str(server.get("sni") or DEFAULT_REALITY_SNI)
    payload = _inbound_payload(server, keys, short_id, sni)

    result = await _panel_request(server["ip"], panel, "POST", "/panel/api/inbounds/add", payload)
    if not result or result.get("success") is False:
        logger.error("[%s] не удалось создать inbound: %s", server["ip"], result)
        return None

    inbounds = await _list_inbounds(server["ip"], panel)
    for inbound in inbounds:
        if _parse_int(inbound.get("port"), 0) == vpn_port:
            logger.info("[%s] inbound создан на порту %s", server["ip"], vpn_port)
            return enrich_inbound(inbound, server["ip"], panel)
    return None


# ────────────────────────────────────────────────────────────
#  Развёртывание и импорт
# ────────────────────────────────────────────────────────────

async def deploy_server(server: dict[str, Any], panel: dict[str, Any] | None = None,
                        timeout: int = 900) -> dict[str, Any]:
    """Полный цикл для одного сервера: SSH → 3x-ui → firewall → inbound."""
    if panel is None:
        panel, _ = load_servers_config()
    panel = _panel_for_server(server, panel)
    result: dict[str, Any] = {
        "success": False,
        "server": server,
        "output": "",
        "error": "",
    }

    if is_placeholder_server(server):
        result["error"] = "Пропущен: укажи реальный IP и SSH-пароль в servers.json / servers.txt"
        return result

    try:
        _require_asyncssh()
        async with await _ssh_connect(server) as conn:
            logger.info("[%s] установка 3x-ui...", server["ip"])
            resp = await conn.run(
                "bash -s",
                input=_install_script(server, panel),
                timeout=timeout,
                check=False,
            )
            result["output"] = (resp.stdout or "")
            if resp.exit_status != 0:
                result["error"] = (
                    (resp.stderr or "")[-4000:]
                    or f"install script exit {resp.exit_status}"
                )
                return result

        details = await ensure_inbound(server, panel)
        if not details:
            result["error"] = "3x-ui установлен, но не удалось создать VLESS Reality inbound"
            return result

        result.update({
            "success": True,
            "inbound": details,
            "panel_url": f"http://{server['ip']}:{panel['port']}",
            "panel_user": panel["username"],
            "panel_pass": panel["password"],
        })
    except Exception as exc:  # noqa: BLE001
        logger.exception("[%s] deploy failed", server.get("ip"))
        result["error"] = str(exc)
    return result


async def import_server_to_db(server: dict[str, Any], details: dict[str, Any],
                              panel: dict[str, Any] | None = None) -> int | None:
    """Создаёт или обновляет Server в БД бота."""
    from app.database import create_server, get_all_servers, update_server

    panel = _panel_for_server(server, panel)
    config_template = json.dumps(
        {
            "inbound_id": details.get("inbound_id"),
            "security": details.get("security"),
            "network": details.get("network"),
            "sni": details.get("sni"),
            "public_key": details.get("public_key"),
            "short_id": details.get("short_id"),
            "short_ids": details.get("short_ids"),
            "flow": details.get("flow"),
            "fingerprint": details.get("fingerprint"),
            "dest": details.get("dest"),
            "panel_port": panel["port"],
            "panel_user": panel["username"],
        },
        ensure_ascii=False,
    )

    existing = await get_all_servers()
    match = next(
        (s for s in existing
         if s.host == server["ip"] and _parse_int(s.port, 0) == _parse_int(server.get("vpn_port"), 443)),
        None,
    )

    if match:
        updated = await update_server(
            match.id,
            name=server.get("name") or match.name,
            protocol=details.get("protocol") or "vless",
            location=server.get("location") or match.location,
            is_active=True,
            config_template=config_template,
        )
        return updated.id if updated else match.id

    created = await create_server(
        name=server.get("name") or f"VPS {server['ip']}",
        host=server["ip"],
        port=_parse_int(server.get("vpn_port"), 443),
        protocol=details.get("protocol") or "vless",
        location=server.get("location") or "",
        is_active=True,
        config_template=config_template,
    )
    return created.id


async def sync_server_from_panel(server: dict[str, Any], panel: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Импортирует уже установленный 3x-ui без повторной установки."""
    panel = _panel_for_server(server, panel)
    inbounds = await _list_inbounds(server["ip"], panel)
    if not inbounds:
        return None

    preferred_port = _parse_int(server.get("vpn_port"), 0)
    selected = next(
        (i for i in inbounds
         if _parse_int(i.get("port"), 0) == preferred_port
         and str(i.get("protocol") or "").lower() in ("vless", "vmess", "trojan", "shadowsocks")),
        None,
    ) or next(
        (i for i in inbounds
         if str(i.get("protocol") or "").lower() in ("vless", "vmess", "trojan", "shadowsocks")),
        None,
    )
    if not selected:
        return None
    return enrich_inbound(selected, server["ip"], panel)


async def deploy_all(servers: list[dict[str, Any]] | None = None,
                     panel: dict[str, Any] | None = None,
                     import_to_db: bool = True,
                     progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Разворачивает все серверы из конфига и импортирует их в БД."""
    if panel is None or servers is None:
        loaded_panel, loaded_servers = load_servers_config()
        panel = panel or loaded_panel
        servers = servers if servers is not None else loaded_servers

    panel = ensure_panel_credentials(panel, servers)
    summary: dict[str, Any] = {
        "total": len(servers),
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "results": [],
        "imported": [],
    }

    if not servers:
        summary["message"] = "В servers.json / servers.txt нет серверов."
        return summary

    for index, server in enumerate(servers, 1):
        name = server.get("name") or server.get("ip")
        if is_placeholder_server(server):
            summary["skipped"] += 1
            summary["results"].append({"server": name, "success": False, "error": "placeholder"})
            if progress:
                progress(f"[{index}/{len(servers)}] {name}: пропущен (placeholder)")
            continue

        if progress:
            progress(f"[{index}/{len(servers)}] {name}: SSH → 3x-ui → inbound...")

        result = await deploy_server(server, panel)
        if result["success"]:
            details = result["inbound"]
            server["deployed"] = True
            server["inbound_id"] = details.get("inbound_id")
            server["public_key"] = details.get("public_key")
            server["short_id"] = details.get("short_id")
            server["sni"] = details.get("sni")
            server["panel_port"] = _parse_int(server.get("panel_port") or panel.get("port"), 2053)
            server["panel_user"] = panel["username"]
            server["panel_pass"] = panel["password"]
            summary["success"] += 1

            if import_to_db:
                try:
                    server_id = await import_server_to_db(server, details, panel)
                    summary["imported"].append({"server": name, "id": server_id})
                    if progress:
                        progress(f"[{index}/{len(servers)}] {name}: ✅ 3x-ui + inbound + БД (server #{server_id})")
                except Exception as exc:  # noqa: BLE001
                    logger.exception("DB import failed for %s", name)
                    if progress:
                        progress(f"[{index}/{len(servers)}] {name}: ⚠️ 3x-ui ok, БД: {exc}")
            else:
                if progress:
                    progress(f"[{index}/{len(servers)}] {name}: ✅ 3x-ui + inbound")
        else:
            summary["failed"] += 1
            if progress:
                progress(f"[{index}/{len(servers)}] {name}: ❌ {result.get('error')}")

        summary["results"].append(result)

    try:
        save_servers_config(panel, servers)
    except OSError as exc:
        logger.warning("Не удалось сохранить servers.json: %s", exc)

    return summary


async def sync_all_to_db(servers: list[dict[str, Any]] | None = None,
                         panel: dict[str, Any] | None = None) -> dict[str, Any]:
    """Импортирует все серверы из servers.json в БД без установки."""
    if panel is None or servers is None:
        loaded_panel, loaded_servers = load_servers_config()
        panel = panel or loaded_panel
        servers = servers if servers is not None else loaded_servers

    summary: dict[str, Any] = {"total": len(servers), "success": 0, "failed": 0, "results": []}
    for server in servers:
        if is_placeholder_server(server):
            summary["failed"] += 1
            summary["results"].append({"server": server.get("ip"), "success": False, "error": "placeholder"})
            continue
        details = await sync_server_from_panel(server, panel)
        if not details:
            summary["failed"] += 1
            summary["results"].append({"server": server.get("ip"), "success": False, "error": "3x-ui API недоступен"})
            continue
        try:
            server_id = await import_server_to_db(server, details, panel)
            summary["success"] += 1
            summary["results"].append({"server": server.get("ip"), "success": True, "id": server_id})
        except Exception as exc:  # noqa: BLE001
            summary["failed"] += 1
            summary["results"].append({"server": server.get("ip"), "success": False, "error": str(exc)})
    return summary


async def check_all_servers(servers: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if servers is None:
        _panel, servers = load_servers_config()
    results: list[dict[str, Any]] = []
    for server in servers:
        if is_placeholder_server(server):
            results.append({
                "server": server.get("ip"),
                "name": server.get("name"),
                "alive": False,
                "error": "placeholder",
            })
            continue
        status = await check_server_ssh(
            server["ip"],
            server["password"],
            _parse_int(server.get("ssh_port"), 22),
        )
        status.update({"server": server.get("ip"), "name": server.get("name")})
        results.append(status)
    return results
