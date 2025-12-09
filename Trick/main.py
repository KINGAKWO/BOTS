import logging
import os
import sqlite3
import threading
import signal
import asyncio
from openai import AsyncOpenAI  # Changed from langchain imports
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes, ApplicationBuilder
import aiosqlite


# Hosting.......................................................................................
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")


HEALTH_SERVER = None
HEALTH_SERVER_THREAD = None


def start_health_server():
    global HEALTH_SERVER
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    server = HTTPServer((host, port), HealthCheckHandler)
    HEALTH_SERVER = server
    print(f"Health check server listening on port {port}")
    server.serve_forever()


def stop_health_server():
    global HEALTH_SERVER
    if HEALTH_SERVER is not None:
        try:
            HEALTH_SERVER.shutdown()
            HEALTH_SERVER.server_close()
            print("Health check server stopped.")
        except Exception as exc:
            print(f"Failed to stop health check server: {exc}")
        finally:
            HEALTH_SERVER = None


# ----------------------------------------------------------------------------------------------

# Bot identity
BOT_USERNAME = "@BiblicalCounselorBot"

# Load environment variables
load_dotenv()
Token = os.getenv("BOT_TOKEN")
if not Token:
    raise ValueError("missing token")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")  # Changed from API_KEY
if not OPENROUTER_API_KEY:
    raise ValueError("missing openrouter key")
ENCRYPTION = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION:
    raise ValueError("missing ENCRYPTION")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Check for missing keys - UPDATED
if not all([Token, OPENROUTER_API_KEY, ENCRYPTION, ADMIN_ID]):
    raise ValueError("Missing Keys in .env file! Check BOT_TOKEN, OPENROUTER_API_KEY, ENCRYPTION_KEY")

# Configure OpenRouter client - NEW
openrouter_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    default_headers={
        "HTTP-Referer": "https://catholic-companion-bot.onrender.com",  # Optional but recommended
        "X-Title": "Biblical Counselor Bot",  # Optional but recommended
    },
)

cipher = Fernet(ENCRYPTION.encode())

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup
DB_FILE = 'ministry.db'
DB_LOCK = asyncio.Lock()

# Model constants - NEW
PRIMARY_MODEL = "google/gemini-2.0-flash-exp:free"  # Primary: Gemini 2.0 Flash Experimental
FALLBACK_MODEL = "amazon/nova-2-lite-v1:free"  # Fallback: Nova 2 Lite


async def init_db():
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp TEXT,
            sender TEXT,
            encrypted_content TEXT
        )''')
        await conn.commit()


async def log_securely(user_id, sender_type, text):
    try:
        encrypted_blob = cipher.encrypt(text.encode()).decode()
        async with DB_LOCK:
            async with aiosqlite.connect(DB_FILE) as conn:
                await conn.execute(
                    "INSERT INTO logs(user_id, timestamp, sender, encrypted_content) VALUES (?,?,?,?)",
                    (user_id, datetime.now().isoformat(), sender_type, encrypted_blob)
                )
                await conn.commit()
    except Exception as e:
        logger.error(f"Logging failed: {e}")


# Global throttle lock and timestamp
LAST_REQUEST_TIME = 0
THROTTLE_LOCK = asyncio.Lock()
THROTTLE_INTERVAL = 2.0  # seconds between requests


async def get_ai_response(user_text, context=None):
    """
    Get a response using OpenRouter with fallback between Gemini 2.0 Flash and Nova 2 Lite.
    """
    global LAST_REQUEST_TIME

    # Throttling logic remains the same
    async with THROTTLE_LOCK:
        now = asyncio.get_event_loop().time()
        elapsed = now - LAST_REQUEST_TIME
        if elapsed < THROTTLE_INTERVAL:
            await asyncio.sleep(THROTTLE_INTERVAL - elapsed)
        LAST_REQUEST_TIME = asyncio.get_event_loop().time()

    # System prompt for spiritual companion
    system_prompt = """You are a warm, wise Catholic spiritual companion.
    1. DOCTRINE: Use the RSV-CE Bible. Stick to the Catechism (CCC).
    2. TONE: Compassionate, like a wise elder or priest. Not robotic.
    3. SAFETY PROTOCOL:
       - If user indicates SELF-HARM, SUICIDE, or ABUSE:
       - Output ONLY this exact string: "FLAG:CRISIS"
       - Do not output spiritual advice in that specific case."""

    # Try primary model first
    try:
        response = await openrouter_client.chat.completions.create(
            model=PRIMARY_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=0.5,
            max_tokens=400
        )
        return response.choices[0].message.content

    except Exception as primary_error:
        error_msg = str(primary_error)
        logger.error(f"Primary model ({PRIMARY_MODEL}) failed: {error_msg}")

        # Try fallback model
        try:
            logger.info(f"Attempting fallback to {FALLBACK_MODEL}")

            # Note: For Nova 2 Lite, you can optionally enable reasoning
            response = await openrouter_client.chat.completions.create(
                model=FALLBACK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ],
                temperature=0.5,
                max_tokens=400,
                # Optional: Uncomment to enable reasoning for Nova 2 Lite
                # extra_body={"reason": True}  # Shows step-by-step reasoning
            )
            return response.choices[0].message.content

        except Exception as fallback_error:
            error_msg = str(fallback_error)
            logger.error(f"Both models failed: {error_msg}")

            # Check for rate limits or quota issues
            if "quota" in error_msg.lower() or "429" in error_msg or "rate limit" in error_msg.lower():
                fallback_msg = (
                    "⚠️ Service temporarily limited. Please try again in a few moments.\n"
                    "You can also consider supporting the bot's development for premium access."
                )
                # Notify admin if available
                if context and ADMIN_ID != 0:
                    try:
                        await context.bot.send_message(
                            chat_id=ADMIN_ID,
                            text=f"⚠️ OpenRouter quota/rate limit hit.\nUser text: {user_text[:100]}...\nError: {error_msg}"
                        )
                    except Exception as alert_exc:
                        logger.error(f"Failed to alert admin: {alert_exc}")
                return fallback_msg

            # Generic error fallback
            return "I am having trouble contemplating right now. Please try again in a moment."


async def safe_admin_alert(bot, admin_id, text):
    if admin_id == 0:
        return False

    delays = [1, 2, 4]
    for attempt, delay in enumerate(delays, start=1):
        try:
            await bot.send_message(chat_id=admin_id, text=text)
            return True
        except Exception as exc:
            logger.error(f"Admin alert attempt {attempt} failed: {exc}")
            await asyncio.sleep(delay)
    return False


# Telegram handlers (unchanged)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_message = (
        f"👋 Hello {user.first_name}!\n\n"
        "I'm Lewis, your spiritual companion bot. "
        "Send me any message and I'll reply thoughtfully.\n\n"
        "I can help find scripture or pray with you. I am an AI, not a priest."
    )
    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_message = (
        "📖 *Bot Help*\n\n"
        "Here's what I can do:\n"
        "• I can help find scripture or pray with you\n"
        "• Crisis safety check: if I detect distress, I'll respond with supportive guidance\n"
        "• Admin alert: I notify the owner if a crisis is flagged\n\n"
        "Commands:\n"
        "• /start – Welcome message\n"
        "• /help – Show this help menu\n\n"
        "Just type any message and I'll reply!"
    )
    await update.message.reply_text(help_message, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    await log_securely(user_id, "USER", user_text)

    ai_reply = await get_ai_response(user_text, context)

    if not ai_reply:
        ai_reply = "I am currently unavailable."

    if "FLAG:CRISIS" in ai_reply:
        final_reply = (
            "I hear deep pain in your words. Please, you are valuable.\n\n"
            "📌 Contact your Priest (680727236) https://t.me/defpatrick or call emergency services immediately."
        )
        if ADMIN_ID != 0:
            alert_message = (
                f"⚠️ Crisis detected!\n\n"
                f"👤 User ID: {user_id}\n"
                f"📝 Message: {user_text}\n"
                f"🤖 AI Reply: {ai_reply}"
            )
            await safe_admin_alert(context.bot, ADMIN_ID, alert_message)
    else:
        final_reply = ai_reply

    await update.message.reply_text(final_reply)
    await log_securely(user_id, "BOT", final_reply)


def main():
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    global HEALTH_SERVER_THREAD
    HEALTH_SERVER_THREAD = threading.Thread(target=start_health_server, daemon=True)
    HEALTH_SERVER_THREAD.start()

    loop.run_until_complete(init_db())

    application = ApplicationBuilder().token(Token).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    try:
        application.run_polling()
    finally:
        stop_health_server()
        try:
            loop.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()