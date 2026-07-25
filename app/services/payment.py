import uuid
from typing import Protocol

import aiohttp

from app.config import config
from app.database import create_payment, update_payment_status


class PaymentProvider(Protocol):
    async def create_invoice(self, payment_id: uuid.UUID, amount: float, description: str, **kwargs) -> dict:
        ...

    async def check_payment(self, provider_payment_id: str) -> str:
        ...


class YooKassaProvider:
    def __init__(self):
        self.shop_id = config.YOOKASSA_SHOP_ID
        self.secret_key = config.YOOKASSA_SECRET_KEY
        self.api_url = "https://api.yookassa.ru/v3"

    async def create_invoice(self, payment_id: uuid.UUID, amount: float, description: str, **kwargs) -> dict:
        auth = aiohttp.BasicAuth(self.shop_id, self.secret_key)
        data = {
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": config.YOOKASSA_RETURN_URL},
            "capture": True,
            "description": description,
            "metadata": {"payment_id": str(payment_id)},
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.api_url}/payments",
                json=data,
                auth=auth,
                headers={"Idempotence-Key": str(uuid.uuid4())},
            ) as resp:
                result = await resp.json()
                return {
                    "pay_url": result.get("confirmation", {}).get("confirmation_url", ""),
                    "provider_payment_id": result.get("id", ""),
                }

    async def check_payment(self, provider_payment_id: str) -> str:
        auth = aiohttp.BasicAuth(self.shop_id, self.secret_key)
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.api_url}/payments/{provider_payment_id}", auth=auth
            ) as resp:
                result = await resp.json()
                status_map = {
                    "succeeded": "completed",
                    "pending": "pending",
                    "waiting_for_capture": "pending",
                    "canceled": "cancelled",
                }
                return status_map.get(result.get("status"), "pending")


class CryptoBotProvider:
    def __init__(self):
        self.token = config.CRYPTOBOT_TOKEN
        self.api_url = "https://pay.crypt.bot/api"

    async def create_invoice(self, payment_id: uuid.UUID, amount: float, description: str, **kwargs) -> dict:
        currency = kwargs.get("currency", "USDT")
        headers = {"Crypto-Pay-API-Token": self.token, "Content-Type": "application/json"}
        data = {
            "asset": currency,
            "amount": str(amount),
            "description": description,
            "payload": str(payment_id),
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.api_url}/createInvoice", json=data, headers=headers
            ) as resp:
                result = await resp.json()
                if result.get("ok"):
                    return {
                        "pay_url": result["result"]["pay_url"],
                        "provider_payment_id": str(result["result"]["invoice_id"]),
                    }
                return {"pay_url": "", "provider_payment_id": ""}

    async def check_payment(self, provider_payment_id: str) -> str:
        headers = {"Crypto-Pay-API-Token": self.token}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.api_url}/getInvoices",
                params={"invoice_ids": provider_payment_id},
                headers=headers,
            ) as resp:
                result = await resp.json()
                if result.get("ok") and result["result"]["items"]:
                    status = result["result"]["items"][0]["status"]
                    return "completed" if status == "paid" else "pending"
                return "pending"


class ManualWalletProvider:
    def __init__(self):
        self.address = config.WALLET_ADDRESS
        self.currency = config.WALLET_CURRENCY

    async def create_invoice(self, payment_id: uuid.UUID, amount: float, description: str, **kwargs) -> dict:
        return {
            "pay_url": "",
            "provider_payment_id": str(payment_id),
            "wallet_address": self.address,
            "currency": self.currency,
            "amount": amount,
        }

    async def check_payment(self, provider_payment_id: str) -> str:
        return "pending"


class PaymentService:
    def __init__(self):
        self.providers: dict[str, PaymentProvider] = {}
        if config.YOOKASSA_SHOP_ID and config.YOOKASSA_SECRET_KEY:
            self.providers["yookassa"] = YooKassaProvider()
        if config.CRYPTOBOT_TOKEN:
            self.providers["cryptobot"] = CryptoBotProvider()
        if config.WALLET_ADDRESS:
            self.providers["wallet"] = ManualWalletProvider()

    async def create_payment(
        self, user_id: int, amount: float, plan: str, provider: str = "yookassa",
        description: str | None = None,
    ) -> dict:
        if provider not in self.providers:
            raise ValueError(f"Payment provider {provider} not available")

        payment = await create_payment(
            user_id=user_id, amount=amount, provider=provider,
            plan=plan, description=description or f"VPN {plan}",
        )
        invoice = await self.providers[provider].create_invoice(
            payment_id=payment.id, amount=amount,
            description=description or f"VPN {plan}",
        )
        pay_url = invoice.get("pay_url", "")
        provider_payment_id = invoice.get("provider_payment_id", "")
        if pay_url:
            await update_payment_status(payment.id, "pending", provider_payment_id=provider_payment_id or str(payment.id))
        result = {"payment": payment, "pay_url": pay_url}
        if provider == "wallet":
            result["wallet"] = {
                "address": config.WALLET_ADDRESS,
                "currency": config.WALLET_CURRENCY,
                "amount": amount,
            }
        return result

    async def check_payment_status(self, payment_id: uuid.UUID) -> str:
        from app.database import get_payment
        payment = await get_payment(payment_id)
        if not payment:
            return "not_found"
        if payment.status in ("completed", "cancelled"):
            return payment.status
        if payment.provider not in self.providers:
            return payment.status
        new_status = await self.providers[payment.provider].check_payment(payment.provider_payment_id or "")
        if new_status != payment.status:
            await update_payment_status(payment_id, new_status)
        return new_status

    def get_available_providers(self) -> list[str]:
        return list(self.providers.keys())


payment_service = PaymentService()
