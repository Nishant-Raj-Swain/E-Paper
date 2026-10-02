import asyncio
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import Response

# Scraper module import
from scraper import get_newspapers_by_language, get_drive_link

# Load environment variables relative to main.py location
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

# Configure logging format for Render visibility
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("epaper_bot")

# Environment Variables
VERIFY_TOKEN = (os.getenv("WEBHOOK_VERIFY_TOKEN") or "nishi7890").strip()
WHATSAPP_TOKEN = (os.getenv("WHATSAPP_ACCESS_TOKEN") or os.getenv("WHATSAPP_TOKEN") or "").strip()
PHONE_NUMBER_ID = (os.getenv("WHATSAPP_PHONE_NUMBER_ID") or os.getenv("PHONE_NUMBER_ID") or "").strip()
APP_SECRET = os.getenv("META_APP_SECRET", "").strip()

# Global locks and memory state
locks = {}
user_states = {}

LANG_MAP = {
    "1": "hindi",
    "2": "english",
    "3": "odia",
    "4": "marathi",
    "5": "bengali"
}


# --- DATABASE & ANALYTICS HELPER FUNCTIONS ---
def init_db():
    """Initializes SQLite tables for user state and analytics tracking."""
    try:
        conn = sqlite3.connect("bot_analytics.db")
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                whatsapp_no TEXT NOT NULL,
                command TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_messages (
                msg_id TEXT PRIMARY KEY,
                processed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to initialize analytics DB: {e}")


def claim_message(msg_id: str) -> bool:
    """Prevents duplicate processing of Meta webhooks."""
    if not msg_id:
        return True
    try:
        conn = sqlite3.connect("bot_analytics.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO processed_messages (msg_id) VALUES (?)", (msg_id,))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as e:
        logger.error(f"Error checking message claim: {e}")
        return True


def log_user_command(whatsapp_no: str, command: str):
    """Logs user interactions for analytics dashboard tracking."""
    try:
        conn = sqlite3.connect("bot_analytics.db")
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO user_logs (whatsapp_no, command, timestamp)
            VALUES (?, ?, ?)
        ''', (whatsapp_no, command.strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log command to analytics DB: {e}")


# --- WHATSAPP HELPER CLASS ---
class WhatsApp:
    """Wrapper class for sending messages using Meta WhatsApp Cloud API."""
    def __init__(self):
        import httpx
        self.client = httpx.AsyncClient(timeout=20.0)

    async def send_text(self, to_phone: str, text_body: str):
        if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
            logger.error("Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID!")
            return

        url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"body": text_body}
        }
        try:
            res = await self.client.post(url, json=payload, headers=headers)
            if res.status_code >= 400:
                logger.error(f"WhatsApp API Error [{res.status_code}]: {res.text}")
        except Exception as e:
            logger.error(f"Failed to send WhatsApp message to {to_phone}: {e}")

    async def send_menu(self, phone: str):
        menu_msg = (
            "📰 *Welcome to Daily ePaper Bot!*\n\n"
            "Please select a language by replying with a number:\n"
            "1️⃣ Hindi Epaper\n"
            "2️⃣ English Epaper\n"
            "3️⃣ Odia Epaper\n"
            "4️⃣ Marathi Epaper\n"
            "5️⃣ Bengali Epaper\n\n"
            "_Type /menu anytime to restart._"
        )
        await self.send_text(phone, menu_msg)

    async def close(self):
        await self.client.aclose()


wa = None


# --- LIFESPAN MANAGER ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global wa
    init_db()
    wa = WhatsApp()

    if not WHATSAPP_TOKEN:
        logger.error("❌ WHATSAPP_TOKEN is missing in environment!")
    else:
        logger.info(f"✅ WHATSAPP_TOKEN loaded successfully! (Length: {len(WHATSAPP_TOKEN)})")

    if not PHONE_NUMBER_ID:
        logger.error("❌ PHONE_NUMBER_ID is missing in environment!")
    else:
        logger.info(f"✅ PHONE_NUMBER_ID loaded successfully: {PHONE_NUMBER_ID}")

    yield

    await wa.close()


app = FastAPI(title="WhatsApp ePaper Assistant", lifespan=lifespan)


# --- MESSAGE PROCESSING HANDLERS ---
async def handle_text(phone: str, text: str):
    state = user_states.get(phone, {})
    mode = state.get("mode")

    # STEP 1: Language Selection Phase
    if mode == "select_lang":
        if text not in LANG_MAP:
            await wa.send_text(phone, "⚠️ Please reply with a valid choice between *1 and 5*.")
            return

        selected_lang = LANG_MAP[text]
        await wa.send_text(phone, f"⏳ Fetching *{selected_lang.upper()}* newspapers...")

        papers = await get_newspapers_by_language(selected_lang)
        if not papers:
            await wa.send_text(phone, "❌ Could not retrieve papers right now. Send `/menu` to try again.")
            user_states[phone] = {}
            return

        user_states[phone] = {
            "mode": "select_paper",
            "lang": selected_lang,
            "papers": papers
        }

        reply = f"📰 *Select a Newspaper ({selected_lang.capitalize()}):*\n\n"
        for idx, paper in enumerate(papers, 1):
            reply += f"*{idx}.* {paper['name']}\n"
        reply += "\n_Reply with the number of your chosen paper (e.g., 1)_"

        await wa.send_text(phone, reply)
        return

    # STEP 2: Newspaper Selection Phase
    if mode == "select_paper":
        if not text.isdigit():
            await wa.send_text(phone, "⚠️ Please reply with a valid number from the list above.")
            return

        idx = int(text) - 1
        papers = state.get("papers", [])

        if idx < 0 or idx >= len(papers):
            await wa.send_text(phone, f"⚠️ Invalid option. Please choose a number between 1 and {len(papers)}.")
            return

        chosen_paper = papers[idx]
        await wa.send_text(phone, f"⏳ Extracting today's link for *{chosen_paper['name']}*...")

        drive_url = await get_drive_link(chosen_paper["link"])

        if drive_url:
            await wa.send_text(
                phone,
                f"✅ *Google Drive Link Ready!*\n\n"
                f"📰 *Paper:* {chosen_paper['name']}\n"
                f"🔗 *Download:* {drive_url}\n\n"
                f"_Type /menu to select another paper._"
            )
        else:
            await wa.send_text(phone, "❌ Couldn't extract today's link. Send `/menu` to try another paper.")

        user_states[phone] = {}
        return

    # Fallback to main menu
    user_states[phone] = {"mode": "select_lang"}
    await wa.send_menu(phone)


async def command(phone: str, text: str):
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd in ("/start", "/help", "/menu", "/cancel"):
        user_states[phone] = {"mode": "select_lang"}
        await wa.send_menu(phone)
        return


async def process_message(message: dict):
    phone = message.get("from", "")
    msg_id = message.get("id", "")

    logger.info(f"Processing incoming message [{msg_id}] from user: {phone}")

    if not claim_message(msg_id):
        logger.info(f"Message ID [{msg_id}] already processed. Skipping duplicate.")
        return

    lock = locks.setdefault(phone, asyncio.Lock())
    async with lock:
        text = (message.get("text", {}) or {}).get("body", "").strip()

        if text:
            log_user_command(whatsapp_no=phone, command=text)

        if text.startswith("/"):
            await command(phone, text)
        elif text:
            await handle_text(phone, text)


# --- WEBHOOK ENDPOINTS ---
@app.get("/webhook")
async def verify(request: Request):
    params = request.query_params
    mode = params.get("hub.mode") or params.get("hub_mode")
    token = params.get("hub.verify_token") or params.get("hub_verify_token")
    challenge = params.get("hub.challenge") or params.get("hub_challenge")

    logger.info(f"Verify Request - Mode: {mode} | Token: {token}")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        logger.info("Webhook verification succeeded.")
        return Response(content=str(challenge), media_type="text/plain", status_code=200)

    logger.warning("Webhook verification failed.")
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def webhook(request: Request, bg_tasks: BackgroundTasks):
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > 1024 * 1024:
            raise HTTPException(status_code=413)

    sig = request.headers.get("x-hub-signature-256", "")

    if APP_SECRET:
        expected = "sha256=" + hmac.new(APP_SECRET.encode(), bytes(buffer), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            logger.warning("Invalid webhook signature from Meta.")
            raise HTTPException(status_code=403)

    payload = json.loads(bytes(buffer))

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                bg_tasks.add_task(process_message, msg)

    return {"status": "accepted"}
