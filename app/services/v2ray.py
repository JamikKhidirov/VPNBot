import json
import uuid
import base64
import secrets
from urllib.parse import quote
from datetime import datetime, timedelta, timezone

import aiohttp

from app.config import config
from app.database import create_vpn_config


class V2RayService:
    def __init__(self):
        self.api_key = config.V2RAY_API_KEY
        self.api_user = config.V2RAY_USER
        self.api_pass = config.V2RAY_PASS

    def generate_uuid(self) -> str:
        return str(uuid.uuid4())

    def generate_keypair(self) -> dict:
        try:
            import subprocess
            result = subprocess.run(
                ["xray", "x25519"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                private_key = lines[0].split(": ")[1].strip()
                public_key = lines[1].split(": ")[1].strip()
                return {"private_key": private_key, "public_key": public_key}
        except Exception:
            pass
        fake_private = secrets.token_hex(32)
        fake_public = secrets.token_hex(32)
        return {"private_key": fake_private, "public_key": fake_public}

    def get_short_id(self) -> str:
        return "6ba85179e30d4fc2"

    # ── Генерация ссылок ───────────────────────────────

    def _gen_vless(self, host: str, port: int, uid: str,
                   security: str = "reality", flow: str = "xtls-rprx-vision",
                   sni: str = "", public_key: str = "", short_id: str = "") -> str:
        params = {
            "type": "tcp", "security": security, "flow": flow,
            "encryption": "none", "sni": quote(sni or host),
            "fp": "chrome", "pbk": quote(public_key),
            "sid": short_id or self.get_short_id(),
        }
        query = "&".join(f"{k}={v}" for k, v in params.items() if v)
        return f"vless://{uid}@{host}:{port}?{query}#VPN-{host}"

    def _gen_vmess(self, host: str, port: int, uid: str) -> str:
        data = {
            "v": "2", "ps": f"VPN-{host}", "add": host, "port": port,
            "id": uid, "aid": "0", "scy": "auto", "net": "tcp",
            "type": "none", "tls": "",
        }
        encoded = base64.b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
        return f"vmess://{encoded}"

    def _gen_ss(self, host: str, port: int, password: str,
                method: str = "chacha20-ietf-poly1305") -> str:
        encoded = base64.b64encode(f"{method}:{password}".encode()).decode()
        return f"ss://{encoded}@{host}:{port}#VPN-{host}"

    def generate_link(self, host: str, port: int, uid: str,
                      protocol: str = "vless", **kwargs) -> str:
        if protocol == "vless":
            return self._gen_vless(host, port, uid, **kwargs)
        elif protocol == "vmess":
            return self._gen_vmess(host, port, uid)
        elif protocol == "shadowsocks":
            return self._gen_ss(host, port, uid.replace("-", ""))
        raise ValueError(f"Unsupported protocol: {protocol}")

    # ── 3x-ui API на конкретном сервере ───────────────

    async def _call_server_api(self, server_host: str, method: str, path: str, data: dict = None) -> dict | None:
        """Вызов API 3x-ui на конкретном VPS сервере"""
        if not server_host:
            return None
        base_url = f"http://{server_host}:2053/panel/api"
        url = f"{base_url}{path}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                login_resp = await session.post(
                    f"http://{server_host}:2053/login",
                    json={"username": self.api_user, "password": self.api_pass},
                    timeout=aiohttp.ClientTimeout(total=10),
                )
                if login_resp.status != 200:
                    return None
            except Exception:
                return None

            try:
                if method == "GET":
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        return await resp.json() if resp.status == 200 else None
                elif method == "POST":
                    async with session.post(url, json=data, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        return await resp.json() if resp.status == 200 else None
            except Exception:
                return None

    async def check_server_health(self, server_host: str) -> dict:
        """Проверяет, доступен ли 3x-ui на сервере."""
        result = {"alive": False, "inbounds": 0, "clients": 0, "error": None}
        try:
            data = await self._call_server_api(server_host, "GET", "/inbounds")
            if data and "obj" in data:
                result["alive"] = True
                result["inbounds"] = len(data["obj"])
                for inbound in data["obj"]:
                    try:
                        settings = json.loads(inbound.get("settings", "{}"))
                        result["clients"] += len(settings.get("clients", []))
                    except Exception:
                        pass
            else:
                result["error"] = "API вернула пустой ответ"
        except Exception as e:
            result["error"] = str(e)
        return result

    async def fetch_inbounds(self, server_host: str) -> list[dict]:
        """Получает все inbounds с 3x-ui сервера."""
        data = await self._call_server_api(server_host, "GET", "/inbounds")
        if not data or "obj" not in data:
            return []
        return data["obj"]

    async def get_online_clients(self, server_host: str) -> list[str]:
        """Получает список онлайн клиентов с сервера 3x-ui."""
        data = await self._call_server_api(server_host, "GET", "/inbounds/onlines")
        if not data:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "obj" in data:
            return data["obj"] if isinstance(data["obj"], list) else []
        return []

    async def get_server_traffic(self, server_host: str) -> dict:
        """Получает трафик по каждому inbound на сервере."""
        inbounds = await self.fetch_inbounds(server_host)
        result = {"total_up": 0, "total_down": 0, "total": 0, "inbounds": []}
        for inbound in inbounds:
            up = inbound.get("up", 0) or 0
            down = inbound.get("down", 0) or 0
            total = inbound.get("total", 0) or 0
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
                "clients": len(json.loads(inbound.get("settings", "{}")).get("clients", [])),
            })
        return result

    async def parse_inbound(self, inbound: dict, server_host: str) -> dict | None:
        """Преобразует inbound из 3x-ui в данные для создания Server."""
        try:
            port = inbound.get("port", 443)
            settings = json.loads(inbound.get("settings", "{}"))
            protocol = inbound.get("protocol", "vless").lower()
            remark = inbound.get("remark", f"Server-{port}")
            # Определяем тип протокола
            proto_map = {
                "vless": "vless", "vmess": "vmess",
                "trojan": "trojan", "shadowsocks": "shadowsocks",
            }
            protocol = proto_map.get(protocol, "vless")

            return {
                "name": remark,
                "host": server_host,
                "port": port,
                "protocol": protocol,
                "location": inbound.get("remark", ""),
                "is_active": True,
            }
        except Exception:
            return None

    async def add_client_to_server(self, server_host: str, server_port: int,
                                   uid: str, email: str,
                                   traffic_gb: int = 200, expiry_days: int = 30) -> bool:
        """Автоматически добавляет клиента в 3x-ui на конкретном VPS"""
        inbounds = await self._call_server_api(server_host, "GET", "/inbounds")
        if not inbounds or "obj" not in inbounds:
            return False

        inbound = next((i for i in inbounds["obj"] if i.get("port") == server_port), None)
        if not inbound:
            inbound = next(iter(inbounds["obj"]), None)
        if not inbound:
            return False

        inbound_id = inbound["id"]
        settings = json.loads(inbound.get("settings", "{}"))
        clients = settings.get("clients", [])

        expiry_time = int((datetime.now(timezone.utc) + timedelta(days=expiry_days)).timestamp() * 1000)
        clients.append({
            "id": uid, "email": email, "flow": "xtls-rprx-vision",
            "totalGB": traffic_gb * 1024**3,
            "expiryTime": expiry_time, "enable": True,
        })
        settings["clients"] = clients

        result = await self._call_server_api(
            server_host, "POST", "/inbounds/update",
            {"id": inbound_id, "settings": json.dumps(settings)},
        )
        return result is not None

    async def remove_client_from_server(self, server_host: str, server_port: int, uid: str) -> bool:
        """Удаляет клиента из 3x-ui на сервере"""
        inbounds = await self._call_server_api(server_host, "GET", "/inbounds")
        if not inbounds or "obj" not in inbounds:
            return False
        inbound = next((i for i in inbounds["obj"] if i.get("port") == server_port), None)
        if not inbound:
            return False

        settings = json.loads(inbound.get("settings", "{}"))
        settings["clients"] = [c for c in settings.get("clients", []) if c.get("id") != uid]

        result = await self._call_server_api(
            server_host, "POST", "/inbounds/update",
            {"id": inbound["id"], "settings": json.dumps(settings)},
        )
        return result is not None

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

        uid = self.generate_uuid()
        keypair = self.generate_keypair()

        link = self.generate_link(
            host=host, port=port, uid=uid, protocol=protocol,
            sni=host, public_key=keypair["public_key"],
            short_id=self.get_short_id(),
        )
        expires_at = datetime.now(timezone.utc) + timedelta(days=duration_days)

        config_data = json.dumps({
            "link": link, "uuid": uid, "server": host,
            "port": port, "protocol": protocol,
            "expires_at": expires_at.isoformat(),
        })

        vpn_config = await create_vpn_config(
            user_id=user_id, server_id=server_id,
            subscription_id=subscription_id,
            config_data=config_data, config_link=link,
            uuid=uid, expires_at=expires_at,
        )

        # Регистрируем клиента в 3x-ui на этом сервере
        try:
            await self.add_client_to_server(
                server_host=host, server_port=port,
                uid=uid, email=f"u{user_id}",
                traffic_gb=200, expiry_days=duration_days,
            )
        except Exception:
            pass  # API недоступен — не критично

        return {
            "id": vpn_config.id, "link": link,
            "config_data": config_data, "uuid": uid,
            "expires_at": expires_at, "host": host, "port": port,
        }

    async def get_user_configs(self, user_id: int) -> list:
        from app.database import get_active_configs
        return await get_active_configs(user_id)


v2ray_service = V2RayService()
