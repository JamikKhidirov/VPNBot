import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: list[int] = field(default_factory=lambda: [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x])

    DB_URL: str = os.getenv("DB_URL", "postgresql+asyncpg://vpnbot:vpnbot@localhost:5432/vpnbot")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    YOOKASSA_SHOP_ID: str = os.getenv("YOOKASSA_SHOP_ID", "")
    YOOKASSA_SECRET_KEY: str = os.getenv("YOOKASSA_SECRET_KEY", "")
    YOOKASSA_RETURN_URL: str = os.getenv("YOOKASSA_RETURN_URL", "https://t.me/your_bot")

    CRYPTOBOT_TOKEN: str = os.getenv("CRYPTOBOT_TOKEN", "")

    TRIAL_DAYS: int = int(os.getenv("TRIAL_DAYS", "3"))

    V2RAY_API_URL: str = os.getenv("V2RAY_API_URL", "http://localhost:10085/xui/inbound")
    V2RAY_API_KEY: str = os.getenv("V2RAY_API_KEY", "")
    V2RAY_USER: str = os.getenv("V2RAY_USER", "admin")
    V2RAY_PASS: str = os.getenv("V2RAY_PASS", "admin")

    DEFAULT_SERVER_HOST: str = os.getenv("DEFAULT_SERVER_HOST", "vpn.example.com")
    DEFAULT_SERVER_PORT: int = int(os.getenv("DEFAULT_SERVER_PORT", "443"))
    DEFAULT_PROTOCOL: str = os.getenv("DEFAULT_PROTOCOL", "vless")

    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "")
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8080"))
    WEBHOOK_PATH: str = "/webhook"
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")

    PAYMENT_PROVIDER: str = os.getenv("PAYMENT_PROVIDER", "yookassa")

    BOT_PROXY: str = os.getenv("BOT_PROXY", "")

    SUB_DOMAIN: str = os.getenv("SUB_DOMAIN", "")
    SUB_PORT: int = int(os.getenv("SUB_PORT", "9090"))

    WALLET_ADDRESS: str = os.getenv("WALLET_ADDRESS", "")
    WALLET_CURRENCY: str = os.getenv("WALLET_CURRENCY", "USDT (TRC20)")
    WALLET_NOTE: str = os.getenv("WALLET_NOTE", "После оплаты нажми «Проверить оплату» или напиши админу")

    @property
    def WEBHOOK_URL(self) -> str:
        return f"{self.WEBHOOK_HOST}{self.WEBHOOK_PATH}"

    @property
    def SUB_URL(self) -> str:
        if self.SUB_DOMAIN:
            domain = self.SUB_DOMAIN
            if "://" not in domain:
                domain = f"http://{domain}"
            return domain
        return f"http://{self.DEFAULT_SERVER_HOST}:{self.SUB_PORT}"


config = Config()
