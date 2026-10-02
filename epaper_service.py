import logging
import os
import tempfile
import httpx
import gdown

logger = logging.getLogger(__name__)


class WhatsAppEpaperService:

    def __init__(self, access_token: str, phone_number_id: str):
        if not access_token or not access_token.strip():
            raise ValueError(
                "WHATSAPP_ACCESS_TOKEN is missing or empty! Check your .env file."
            )

        self.access_token = access_token.strip()
        self.phone_number_id = phone_number_id
        self.base_url = (
            f"https://graph.facebook.com/v21.0/{self.phone_number_id}"
        )
        self.headers = {"Authorization": f"Bearer {self.access_token}"}

    async def download_from_drive(self, drive_url: str, save_path: str) -> bool:
        """Downloads today's ePaper PDF from a Google Drive URL to local temp storage."""
        try:
            # gdown handles extracting Google Drive file IDs and downloading directly
            output = gdown.download(url=drive_url, output=save_path, quiet=True, fuzzy=True)
            if output and os.path.exists(save_path):
                return True
            logger.warning(f"Failed to download Google Drive PDF from: {drive_url}")
            return False
        except Exception as e:
            logger.error(f"Error downloading ePaper from Drive: {e}")
            return False

    async def upload_to_tmpfiles(self, file_path: str) -> str | None:
        """Uploads local PDF file to tmpfiles.org and returns direct download link."""
        url = "https://tmpfiles.org/api/v1/upload"

        async with httpx.AsyncClient(timeout=30.0) as client:
            with open(file_path, "rb") as f:
                files = {"file": f}
                res = await client.post(url, files=files)

            if res.status_code == 200:
                data = res.json()
                page_url = data.get("data", {}).get("url")
                if page_url:
                    # Convert page URL to direct download URL (requires /dl/)
                    return page_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")

            logger.error(f"tmpfiles.org upload failed: {res.text}")
            return None

    async def send_epaper_document(
        self, recipient_phone: str, paper_name: str, drive_url: str
    ) -> bool:
        """Orchestrates Drive download, tmpfiles hosting, and WhatsApp PDF document dispatch."""
        clean_name = paper_name.lower().replace(" ", "_")
        temp_filename = f"{clean_name}_epaper.pdf"

        # Safe cross-platform temporary file path (Windows & Linux compatible)
        local_path = os.path.join(tempfile.gettempdir(), temp_filename)

        try:
            # 1. Download PDF from Google Drive
            if not await self.download_from_drive(drive_url, local_path):
                return False

            # 2. Upload PDF to tmpfiles.org to obtain direct download URL for Meta API
            download_url = await self.upload_to_tmpfiles(local_path)
            if not download_url:
                return False

            # 3. Send Document Message via WhatsApp Cloud API
            message_url = f"{self.base_url}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient_phone,
                "type": "document",
                "document": {
                    "link": download_url,
                    "filename": f"{paper_name} Today.pdf",
                    "caption": (
                        f"📰 Here is today's official ePaper edition for"
                        f" *{paper_name.upper()}*!"
                    ),
                },
            }

            async with httpx.AsyncClient(timeout=20.0) as client:
                res = await client.post(
                    message_url, headers=self.headers, json=payload
                )
                if res.status_code == 200:
                    logger.info(f"Successfully sent PDF document '{paper_name}' to {recipient_phone}")
                    return True
                
                logger.error(f"Failed to send WhatsApp document [{res.status_code}]: {res.text}")
                return False

        finally:
            # Clean up local temporary file safely
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except OSError as e:
                    logger.warning(f"Failed to delete local temp file: {e}")
