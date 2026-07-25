import json
import os
import logging

import asyncssh

logger = logging.getLogger(__name__)

SERVERS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "servers.json")


def load_vps_servers() -> list[dict]:
    if not os.path.exists(SERVERS_FILE):
        return []
    with open(SERVERS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_vps_servers(servers: list[dict]):
    with open(SERVERS_FILE, "w", encoding="utf-8") as f:
        json.dump(servers, f, indent=4, ensure_ascii=False)


async def install_3xui_on_server(ip: str, password: str, port: int = 22) -> dict:
    commands = [
        "apt update -y",
        "apt install -y curl wget ufw",
        "ufw allow 22/tcp",
        "ufw allow 80/tcp",
        "ufw allow 443/tcp",
        "ufw allow 2053/tcp",
        "ufw --force enable",
        "bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)",
    ]
    result = {"success": False, "output": "", "error": ""}
    try:
        async with asyncssh.connect(
            host=ip,
            port=port,
            username="root",
            password=password,
            known_hosts=None,
            connect_timeout=15,
        ) as conn:
            for cmd in commands:
                logger.info(f"[{ip}] Running: {cmd}")
                resp = await conn.run(cmd, timeout=120)
                result["output"] += f"$ {cmd}\n{resp.stdout}\n"
                if resp.returncode != 0 and "ufw" not in cmd:
                    result["error"] = f"Command failed: {cmd}\n{resp.stderr}"
                    return result
                if resp.stderr:
                    result["output"] += f"STDERR: {resp.stderr}\n"
            result["success"] = True
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[{ip}] SSH failed: {e}")
    return result


async def check_server_ssh(ip: str, password: str, port: int = 22) -> dict:
    result = {"alive": False, "error": ""}
    try:
        async with asyncssh.connect(
            host=ip,
            port=port,
            username="root",
            password=password,
            known_hosts=None,
            connect_timeout=10,
        ) as conn:
            resp = await conn.run("uname -a", timeout=10)
            if resp.returncode == 0:
                result["alive"] = True
                result["os"] = resp.stdout.strip()
    except Exception as e:
        result["error"] = str(e)
    return result
