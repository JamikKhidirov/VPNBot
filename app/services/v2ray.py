import base64
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

import aiohttp

from app.config import config
from app.database import create_vpn_config

logger = logging.getLogger(__name__)


def _json_field(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


class V2RayService:
    def __init__(self):
        self.api_key = config.V2RAY_API_KEY
        self.api_user = config.V2RAY_USER
        self.api_pass = config.V2RAY_PASS

    # ── UUID / ключи ──────────────────────────────────

    def generate_uuid(self) -> str:
        return str(uuid.uuid4())

    def generate_keypair(self) -> dict:
        try:
            import subprocess

            result = subprocess.run(
                ["xray", "x25519"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                private_key = ""
                public_key = ""
                for line in result.stdout.splitlines():
                    low = line.lower()
                    if "private" in low and ":" in line:
                        private_key = line.split(":", 1)[1].strip()
                    elif "public" in low and ":" in line:
                        public_key = line.split(":", 1)[1].strip()
                if private_key:
                    if not public_key:
                        try:
                            from app.services.vps_deploy import derive_public_key

                            public_key = derive_public_key(private_key)
                        except Exception:  # noqa: BLE001
                            public_key = ""
                    return {"private_key": private_key, "public_key": public_key}
        except Exception:  # noqa: BLE001
            pass

        # Локального xray может не быть (например, бот запущен на Windows).
        # В этом случае используем ключи inbound, сохранённые при развёртывании.
        return {"private_key": secrets.token_hex(32), "public_key": secrets.token_hex(32)}

    def get_short_id(self) -> str:
        return secrets.token_hex(4)

    # ── Панель 3x-ui ──────────────────────────────────

    def _panel_settings(self, host: str) -> dict:
        panel = {
            "username": config.V2RAY_USER,
            "password": config.V2RAY_PASS,
            "port": config.V2RAY_PANEL_PORT,
            "scheme": config.V2RAY_PANEL_SCHEME,
            "path": config.V2RAY_PANEL_PATH.strip("/"),
        }
        try:
            from app.services.vps_deploy import load_servers_config

            loaded_panel, servers = load_servers_config()
            panel.update({
                "username": loaded_panel.get("username") or panel["username"],
                "password": loaded_panel.get("password") or panel["password"],
                "port": int(loaded_panel.get("port") or panel["port"]),
                "scheme": loaded_panel.get("scheme") or panel["scheme"],
            })
            match = next(
                (s for s in servers if s.get("ip") == host or s.get("domain") == host),
                None,
            )
            if match:
                panel.update({
                    "username": match.get("panel_user") or panel["username"],
                    "password": match.get("panel_pass") or panel["password"],
                    "port": int(match.get("panel_port") or panel["port"]),
                })
        except Exception:  # noqa: BLE001
            pass
        return panel

    def _base_url(self, host: str, panel: dict) -> str:
        path = f"/{panel['path'].strip('/')}" if panel.get("path") else ""
        return f"{panel.get('scheme', 'http')}://{host}:{int(panel.get('port', 2053))}{path}"

    async def _api_request(self, host: str, method: str, path: str,
                           data: dict | None = None, timeout: int = 20):
        if not host:
            return None
        panel = self._panel_settings(host)
        base = self._base_url(host, panel)
        connector = aiohttp.TCPConnector(ssl=False)
        jar = aiohttp.CookieJar(unsafe=True)
        headers = {"Accept": "application/json", "User-Agent": "VPNBot/2.0"}
        client_timeout = aiohttp.ClientTimeout(total=timeout)

        try:
            async with aiohttp.ClientSession(
                connector=connector, cookie_jar=jar, timeout=client_timeout
            ) as session:
                async with session.post(
                    f"{base}/login",
                    json={"username": panel["username"], "password": panel["password"]},
                    headers=headers,
                ) as login_resp:
                    if login_resp.status != 200:
                        return None
                    try:
                        login_data = await login_resp.json(content_type=None)
                    except Exception:  # noqa: BLE001
                        login_data = {}
                    if isinstance(login_data, dict) and login_data.get("success") is False:
                        return None

                async with session.request(
                    method, f"{base}{path}", json=data, headers=headers
                ) as resp:
                    if resp.status != 200:
                        logger.warning("3x-ui API %s %s -> HTTP %s (%s)", method, path, resp.status, host)
                        return None
                    try:
                        payload = await resp.json(content_type=None)
                    except Exception:  # noqa: BLE001
                        return None
                    return payload if isinstance(payload, dict) else {"obj": payload}
        except Exception as exc:  # noqa: BLE001
            logger.debug("3x-ui API error %s: %s", host, exc)
            return None

    async def _call_server_api(self, server_host: str, method: str, path: str,
                               data: dict = None) -> dict | None:
        """Совместимый alias."""
        return await self._api_request(server_host, method, path, data)

    async def _list_inbounds(self, host: str, timeout: int = 20) -> list[dict]:
        data = await self._api_request(host, "GET", "/panel/api/inbounds/list", timeout=timeout)
        if not data:
            return []
        obj = data.get("obj")
        return obj if isinstance(obj, list) else []

    async def check_server_health(self, server_host: str) -> dict:
        result = {"alive": False, "inbounds": 0, "clients": 0, "error": None}
        inbounds = await self._list_inbounds(server_host)
        if inbounds:
            result["alive"] = True
            result["inbounds"] = len(inbounds)
            for inbound in inbounds:
                settings = _json_field(inbound.get("settings"))
                result["clients"] += len(settings.get("clients", []) or [])
        else:
            result["error"] = "3x-ui API не отвечает или inbound-ов нет"
        return result

    async def fetch_inbounds(self, server_host: str) -> list[dict]:
        return await self._list_inbounds(server_host)

    async def get_online_clients(self, server_host: str) -> list[str]:
        data = await self._api_request(server_host, "GET", "/panel/api/inbounds/onlines")
        if not data:
            return []
        obj = data.get("obj")
        if isinstance(obj, list):
            return [str(x) for x in obj]
        if isinstance(data, list):
            return [str(x) for x in data]
        return []

    async def get_server_traffic(self, server_host: str) -> dict:
        inbounds = await self._list_inbounds(server_host)
        result = {"total_up": 0, "total_down": 0, "total": 0, "inbounds": []}
        for inbound in inbounds:
            up = inbound.get("up", 0) or 0
            down = inbound.get("down", 0) or 0
            total = inbound.get("total", 0) or 0
            settings = _json_field(inbound.get("settings"))
            result["total_up"] += up
            result["total_down"] += down
            result["total"] += total
            result["inbounds"].append({
                "remark": inbound.get("remark", ""),
                "port": inbound.get("port", 0),
                "protocol": inbound.get("protocol", ""),
                "up": up,
                "down": down,
                "total": total,
                "clients": len(settings.get("clients", []) or []),
            })
        return result

    async def parse_inbound(self, inbound: dict, server_host: str) -> dict | None:
        """Преобразует inbound 3x-ui в данные для создания Server."""
        try:
            from app.services.vps_deploy import enrich_inbound

            panel = self._panel_settings(server_host)
            details = enrich_inbound(inbound, server_host, panel)
            return {
                "name": details.get("remark") or f"Server-{details['port']}",
                "host": server_host,
                "port": details["port"],
                "protocol": details["protocol"],
                "location": details.get("remark", ""),
                "is_active": True,
                "config_template": json.dumps(details, ensure_ascii=False),
            }
        except Exception:  # noqa: BLE001
            return None

    # ── Клиенты ───────────────────────────────────────

    def _select_inbound(self, inbounds: list[dict], server_port: int,
                        server=None) -> dict | None:
        template = {}
        if server is not None and getattr(server, "config_template", None):
            try:
                template = json.loads(server.config_template or "{}")
            except (TypeError, json.JSONDecodeError):
                template = {}

        inbound_id = template.get("inbound_id")
        if inbound_id is not None:
            match = next((i for i in inbounds if str(i.get("id")) == str(inbound_id)), None)
            if match:
                return match

        allowed = {"vless", "vmess", "trojan", "shadowsocks"}
        match = next(
            (i for i in inbounds
             if int(i.get("port") or 0) == int(server_port or 0)
             and str(i.get("protocol") or "").lower() in allowed),
            None,
        )
        if match:
            return match
        return next(
            (i for i in inbounds if str(i.get("protocol") or "").lower() in allowed),
            None,
        )

    def _build_client(self, protocol: str, uid: str, email: str,
                      traffic_gb: int, expiry_days: int, flow: str) -> dict:
        expiry_ms = int(
            (datetime.now(timezone.utc) + timedelta(days=expiry_days)).timestamp() * 1000
        )
        client = {
            "email": email,
            "limitIp": 0,
            "totalGB": int(traffic_gb * 1024 ** 3),
            "expiryTime": expiry_ms,
            "enable": True,
            "tgId": "",
            "subId": secrets.token_hex(8),
            "comment": "VPNBot",
            "reset": 0,
        }
        if protocol == "shadowsocks":
            client["password"] = uid.replace("-", "")
            client["method"] = "chacha20-ietf-poly1305"
        else:
            client["id"] = uid
            client["flow"] = flow
        return client

    async def add_client_to_server(self, server_host: str, server_port: int,
                                   uid: str, email: str,
                                   traffic_gb: int = 200, expiry_days: int = 30,
                                   inbound: dict | None = None,
                                   server=None) -> dict | None:
        """Добавляет клиента в inbound и возвращает его расширенные данные."""
        from app.services.vps_deploy import enrich_inbound

        panel = self._panel_settings(server_host)
        inbounds = await self._list_inbounds(server_host)
        target = inbound or self._select_inbound(inbounds, server_port, server)
        if not target:
            return None

        details = enrich_inbound(target, server_host, panel)
        protocol = details.get("protocol") or "vless"
        flow = details.get("flow") or ""
        if protocol != "vless":
            flow = ""
        client = self._build_client(protocol, uid, email, traffic_gb, expiry_days, flow)

        # Основной путь: addClient (не перезаписывает inbound целиком).
        added = await self._api_request(
            server_host,
            "POST",
            "/panel/api/inbounds/addClient",
            {"id": target.get("id"), "settings": json.dumps({"clients": [client]}, ensure_ascii=False)},
        )
        if added and added.get("success") is not False:
            return details

        # Fallback: полное обновление inbound.
        settings = _json_field(target.get("settings"))
        clients = list(settings.get("clients") or [])
        clients.append(client)
        settings["clients"] = clients
        payload = dict(target)
        payload["settings"] = json.dumps(settings, ensure_ascii=False)
        for key in ("streamSettings", "sniffing", "allocate"):
            if isinstance(payload.get(key), dict):
                payload[key] = json.dumps(payload[key], ensure_ascii=False)

        updated = await self._api_request(
            server_host,
            "POST",
            f"/panel/api/inbounds/update/{target.get('id')}",
            payload,
        )
        if updated and updated.get("success") is not False:
            return details

        updated = await self._api_request(
            server_host,
            "POST",
            "/panel/api/inbounds/update",
            {**payload, "id": target.get("id")},
        )
        return details if updated and updated.get("success") is not False else None

    async def remove_client_from_server(self, server_host: str, server_port: int, uid: str) -> bool:
        inbounds = await self._list_inbounds(server_host)
        target = self._select_inbound(inbounds, server_port)
        if not target:
            return False

        deleted = await self._api_request(
            server_host,
            "POST",
            f"/panel/api/inbounds/{target.get('id')}/delClient/{uid}",
        )
        if deleted and deleted.get("success") is not False:
            return True

        settings = _json_field(target.get("settings"))
        settings["clients"] = [
            c for c in (settings.get("clients") or [])
            if c.get("id") != uid and c.get("password") != uid.replace("-", "")
        ]
        payload = dict(target)
        payload["settings"] = json.dumps(settings, ensure_ascii=False)
        for key in ("streamSettings", "sniffing", "allocate"):
            if isinstance(payload.get(key), dict):
                payload[key] = json.dumps(payload[key], ensure_ascii=False)
        updated = await self._api_request(
            server_host,
            "POST",
            f"/panel/api/inbounds/update/{target.get('id')}",
            payload,
        )
        return bool(updated and updated.get("success") is not False)

    # ── Генерация ссылок ──────────────────────────────

    def _fragment(self, details: dict | None, host: str) -> str:
        details = details or {}
        label = details.get("remark") or details.get("name") or f"VPN-{host}"
        location = details.get("location") or ""
        if location and location not in label:
            label = f"{location} | {label}"
        return quote(label, safe="")

    def _build_link(self, host: str, details: dict, uid: str, email: str = "") -> str:
        protocol = str(details.get("protocol") or "vless").lower()
        port = int(details.get("port") or 443)
        security = str(details.get("security") or "none")
        network = str(details.get("network") or "tcp")
        sni = str(details.get("sni") or host)
        public_key = str(details.get("public_key") or "")
        short_id = str(details.get("short_id") or "")
        flow = str(details.get("flow") or "")
        fingerprint = str(details.get("fingerprint") or "chrome")
        fragment = self._fragment(details, host)

        if protocol == "vless":
            params = {
                "type": network,
                "security": security,
                "encryption": "none",
                "headerType": "none",
            }
            if security in ("reality", "tls"):
                params["sni"] = sni
                params["fp"] = fingerprint
            if security == "reality":
                params["pbk"] = public_key
                params["sid"] = short_id
                params["spx"] = "/"
            if flow:
                params["flow"] = flow
            if network == "ws":
                params["path"] = details.get("path") or "/"
                params["host"] = sni
            elif network == "grpc":
                params["serviceName"] = details.get("grpc_service") or ""
                params["mode"] = "gun"
            query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
            return f"vless://{uid}@{host}:{port}?{query}#{fragment}"

        if protocol == "vmess":
            data = {
                "v": "2",
                "ps": details.get("remark") or f"VPN-{host}",
                "add": host,
                "port": str(port),
                "id": uid,
                "aid": "0",
                "scy": "auto",
                "net": network,
                "type": "none",
                "host": sni if network in ("ws", "http") else "",
                "path": details.get("path") or "",
                "tls": "tls" if security in ("tls", "reality") else "",
                "sni": sni,
                "alpn": "",
                "fp": fingerprint,
            }
            encoded = base64.b64encode(
                json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
            ).decode()
            return f"vmess://{encoded}"

        if protocol == "trojan":
            params = {
                "security": "tls" if security in ("tls", "reality") else "none",
                "sni": sni,
                "type": network,
                "fp": fingerprint,
            }
            if network == "ws":
                params["path"] = details.get("path") or "/"
                params["host"] = sni
            query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
            return f"trojan://{uid}@{host}:{port}?{query}#{fragment}"

        if protocol in ("shadowsocks", "ss"):
            method = details.get("method") or "chacha20-ietf-poly1305"
            password = details.get("password") or uid.replace("-", "")
            encoded = base64.b64encode(f"{method}:{password}".encode()).decode()
            return f"ss://{encoded}@{host}:{port}#{fragment}"

        raise ValueError(f"Unsupported protocol: {protocol}")

    def _gen_vless(self, host: str, port: int, uid: str,
                   security: str = "reality", flow: str = "xtls-rprx-vision",
                   sni: str = "", public_key: str = "", short_id: str = "") -> str:
        return self._build_link(host, {
            "protocol": "vless",
            "port": port,
            "security": security,
            "network": "tcp",
            "flow": flow,
            "sni": sni or host,
            "public_key": public_key,
            "short_id": short_id or self.get_short_id(),
            "fingerprint": "chrome",
            "remark": f"VPN-{host}",
        }, uid)

    def _gen_vmess(self, host: str, port: int, uid: str) -> str:
        return self._build_link(host, {
            "protocol": "vmess",
            "port": port,
            "security": "none",
            "network": "tcp",
            "remark": f"VPN-{host}",
        }, uid)

    def _gen_ss(self, host: str, port: int, password: str,
                method: str = "chacha20-ietf-poly1305") -> str:
        encoded = base64.b64encode(f"{method}:{password}".encode()).decode()
        return f"ss://{encoded}@{host}:{port}#VPN-{host}"

    def generate_link(self, host: str, port: int, uid: str,
                      protocol: str = "vless", **kwargs) -> str:
        if protocol == "vless":
            return self._gen_vless(host, port, uid, **kwargs)
        if protocol == "vmess":
            return self._gen_vmess(host, port, uid)
        if protocol in ("shadowsocks", "ss"):
            return self._gen_ss(host, port, uid.replace("-", ""))
        raise ValueError(f"Unsupported protocol: {protocol}")

    # ── Создание конфига ──────────────────────────────

    async def create_user_config(
        self, user_id: int, server_id: int,
        subscription_id: int | None = None,
        duration_days: int = 30,
        server_host: str | None = None,
        server_port: int = 443,
    ) -> dict:
        from app.database import get_server

        server = await get_server(server_id) if server_id else None
        host = server_host or (server.host if server else "localhost")
        port = server_port or (server.port if server else 443)
        protocol = server.protocol if server else "vless"
        email = f"u{user_id}-{secrets.token_hex(3)}"
        uid = self.generate_uuid()
        details: dict | None = None
        client_added = False

        try:
            inbounds = await self._list_inbounds(host, timeout=5)
            inbound = self._select_inbound(inbounds, port, server)
            if inbound:
                details = await self.add_client_to_server(
                    server_host=host,
                    server_port=port,
                    uid=uid,
                    email=email,
                    traffic_gb=200,
                    expiry_days=duration_days,
                    inbound=inbound,
                    server=server,
                )
                client_added = details is not None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось добавить клиента на %s: %s", host, exc)

        if details:
            protocol = details.get("protocol") or protocol
            port = int(details.get("port") or port)
            link = self._build_link(host, details, uid, email)
        else:
            # Fallback: используем параметры inbound, сохранённые при развёртывании.
            template: dict = {}
            if server is not None and getattr(server, "config_template", None):
                try:
                    template = json.loads(server.config_template or "{}")
                except (TypeError, json.JSONDecodeError):
                    template = {}
            if template.get("public_key") or template.get("security"):
                template.setdefault("protocol", protocol)
                template.setdefault("port", port)
                template.setdefault("host", host)
                link = self._build_link(host, template, uid, email)
            else:
                keypair = self.generate_keypair()
                link = self.generate_link(
                    host=host,
                    port=port,
                    uid=uid,
                    protocol=protocol,
                    sni=host,
                    public_key=keypair["public_key"],
                    short_id=self.get_short_id(),
                )

        expires_at = datetime.now(timezone.utc) + timedelta(days=duration_days)
        config_data = json.dumps({
            "link": link,
            "uuid": uid,
            "email": email,
            "server": host,
            "port": port,
            "protocol": protocol,
            "inbound_id": (details or {}).get("inbound_id"),
            "public_key": (details or {}).get("public_key", ""),
            "short_id": (details or {}).get("short_id", ""),
            "sni": (details or {}).get("sni", ""),
            "client_added": client_added,
            "expires_at": expires_at.isoformat(),
        }, ensure_ascii=False)

        vpn_config = await create_vpn_config(
            user_id=user_id,
            server_id=server_id,
            subscription_id=subscription_id,
            config_data=config_data,
            config_link=link,
            uuid=uid,
            expires_at=expires_at,
        )

        return {
            "id": vpn_config.id,
            "link": link,
            "config_data": config_data,
            "uuid": uid,
            "expires_at": expires_at,
            "host": host,
            "port": port,
            "client_added": client_added,
        }

    async def get_user_configs(self, user_id: int) -> list:
        from app.database import get_active_configs

        return await get_active_configs(user_id)


v2ray_service = V2RayService()
