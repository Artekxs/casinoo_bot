import aiohttp
import logging

logger = logging.getLogger(__name__)

class CryptoBotPay:
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://pay.crypt.bot/api"

    async def create_invoice(self, amount: float, user_id: int, currency: str = "USDT", description: str = None):
        url = f"{self.base_url}/createInvoice"
        headers = {"Crypto-Pay-API-Token": self.token}
        payload = {
            "asset": currency,
            "amount": str(amount),
            "paid_btn_name": "openBot",
            "paid_btn_url": "https://t.me/your_bot",
        }
        if description:
            payload["description"] = description

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, headers=headers) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        result = data["result"]
                        return {
                            "invoice_id": result["invoice_id"],
                            "url": result["pay_url"],
                            "amount": float(result["amount"]),
                            "asset": result["asset"],
                            "status": result["status"]
                        }
                    else:
                        logger.error(f"CryptoBot error: {data}")
                        return None
            except Exception as e:
                logger.error(f"Request error: {e}")
                return None

    async def get_invoice_status(self, invoice_id: int):
        url = f"{self.base_url}/getInvoices"
        headers = {"Crypto-Pay-API-Token": self.token}
        payload = {"invoice_ids": [invoice_id]}

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, headers=headers) as resp:
                    data = await resp.json()
                    if data.get("ok") and data["result"]["items"]:
                        invoice = data["result"]["items"][0]
                        return {
                            "status": invoice["status"],
                            "paid_amount": float(invoice.get("paid_amount", 0)),
                            "asset": invoice["asset"]
                        }
                    return None
            except Exception as e:
                logger.error(f"Status check error: {e}")
                return None
