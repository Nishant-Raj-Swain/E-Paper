import logging
import os
import re
import httpx

logger = logging.getLogger("epaper_bot")


class WhatsApp:

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15.0)

    @property
    def phone_number_id(self) -> str:
        """Dynamically fetch and sanitize phone number ID to avoid empty or invalid base URLs."""
        phone_id = (
            os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
            or os.getenv("PHONE_NUMBER_ID", "")
        ).strip("/ ")

        if not phone_id:
            logger.warning("PHONE_NUMBER_ID env variable missing! Ensure it is set in Render.")
        return phone_id

    @property
    def base_url(self) -> str:
        """Dynamically construct base URL for Meta Graph API v21.0."""
        return f"https://graph.facebook.com/v21.0/{self.phone_number_id}"

    @property
    def access_token(self) -> str:
        """Dynamically fetch token to ensure latest environment variables are used."""
        token = (
            os.getenv("WHATSAPP_TOKEN", "")
            or os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        )
        return token.strip()

    @property
    def headers(self) -> dict:
        """Generate fresh authorization headers for each outgoing request."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def text(self, phone: str, body: str):
        """Sends a formatted text message to a user via Meta Cloud API."""
        if hasattr(body, "content"):
            clean_body = body.content
        else:
            clean_body = body

        if isinstance(clean_body, list):
            text_parts = []
            for block in clean_body:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    text_parts.append(block)
            clean_body = "\n".join(text_parts)

        clean_body = str(clean_body)

        if len(clean_body) > 4000:
            clean_body = (
                clean_body[:3990] + "\n\n*(Message truncated due to length)*"
            )

        # SANITIZE PHONE NUMBER: Remove '+', spaces, and dashes
        clean_phone = re.sub(r"[^\d]", "", str(phone))

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "text",
            "text": {"preview_url": False, "body": clean_body},
        }

        logger.info(f"Sending WhatsApp message to {clean_phone}")

        response = await self.client.post(
            f"{self.base_url}/messages", headers=self.headers, json=payload
        )

        if response.status_code != 200:
            logger.error(
                f"Meta API Error ({response.status_code}): {response.text}"
            )
        else:
            logger.info(f"Meta API Success: {response.json()}")

        return response

    async def menu(self, to: str):
        """Sends the main language selection menu to the user."""
        menu_text = (
            "📰 *Welcome to Daily ePaper Bot!*\n\n"
            "Please select your preferred language by replying with a number:\n"
            "1️⃣ Hindi Epaper\n"
            "2️⃣ English Epaper\n"
            "3️⃣ Odia Epaper\n"
            "4️⃣ Marathi Epaper\n"
            "5️⃣ Bengali Epaper\n\n"
            "_Type /menu anytime to restart navigation._"
        )
        await self.text(to, menu_text)

    async def close(self):
        """Closes the HTTPX client session during app shutdown."""
        await self.client.aclose()
