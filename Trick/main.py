import logging
import os
import sqlite3  # Kept for compatibility, but aiosqlite is used for async operations
import threading
import signal
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes, ApplicationBuilder

import aiosqlite  # Async-safe DB operations


# Hosting.......................................................................................
# this class creates a dummy web server so Render doesn't kill the bot
class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple health check HTTP handler."""

    def do_GET(self):
        """Respond to GET requests with a basic health message."""
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")


HEALTH_SERVER = None
HEALTH_SERVER_THREAD = None


def start_health_server():
    """
    Start the health check HTTP server in the current thread.

    Uses the PORT environment variable (default 8080). The server reference is
    stored globally to allow graceful shutdown via HEALTH_SERVER.shutdown().
    """
    global HEALTH_SERVER
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    server = HTTPServer((host, port), HealthCheckHandler)
    HEALTH_SERVER = server
    print(f"Health check server listening on port {port}")
    server.serve_forever()


def stop_health_server():
    """
    Stop the health check server gracefully if it is running.

    Calls shutdown() and server_close() on the HTTPServer instance.
    """
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
API = os.getenv("API_KEY")
ENCRYPTION = os.getenv("ENCRYPTION_KEY")
# Default to 0 if not set, ensuring int type
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Check for missing keys
if not all([Token, API, ENCRYPTION]):
    raise ValueError("Missing Keys in .env file!")

# Configure Gemini and encryption
# Note: Ensure you are using the latest google-genai SDK
client = genai.Client(api_key=API)
cipher = Fernet(ENCRYPTION.encode())

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup
DB_FILE = 'ministry.db'

# Async DB lock for thread safety when used alongside the HTTP server thread
DB_LOCK = asyncio.Lock()


async def init_db():
    """
    Initialize the SQLite database asynchronously.

    Creates the 'logs' table if it does not exist.
    """
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
    """
    Encrypt and log content to the database asynchronously.

    Parameters
    ----------
    user_id : int
        Telegram user ID.
    sender_type : str
        Either "USER" or "BOT".
    text : str
        Plaintext message to be encrypted and stored.
    """
    try:
        encrypted_blob = cipher.encrypt(text.encode()).decode()
        async with DB_LOCK:  # Ensure thread-safety if other threads interact
            async with aiosqlite.connect(DB_FILE) as conn:
                await conn.execute(
                    "INSERT INTO logs(user_id, timestamp, sender, encrypted_content) VALUES (?,?,?,?)",
                    (user_id, datetime.now().isoformat(), sender_type, encrypted_blob)
                )
                await conn.commit()
    except Exception as e:
        logger.error(f"Logging failed: {e}")


async def get_gemini_response(user_text):
    """
    Get a response from Gemini asynchronously.

    Parameters
    ----------
    user_text : str
        The user's input text.

    Returns
    -------
    str
        The model's response or an error message if the call fails.
    """
    try:
        response = await client.aio.models.generate_content(
            model='gemini-2.0-flash',
            contents=user_text,  # Pass user text directly
            config=types.GenerateContentConfig(
                system_instruction="""
You are a warm, wise Catholic spiritual companion.
1. DOCTRINE: Use the RSV-CE Bible. Stick to the Catechism (CCC).
2. TONE: Compassionate, like a wise elder. Not robotic.
3. SAFETY PROTOCOL:
   - If user indicates SELF-HARM, SUICIDE, or ABUSE:
   - Output ONLY this exact string: "FLAG:CRISIS"
   - Do not output spiritual advice in that specific case.
""",
                max_output_tokens=400,
                top_k=2,
                top_p=0.5,
                temperature=0.5,
                # Removed 'application/json' so the bot replies in normal text
                stop_sequences=['\n\n\n'],
            ),
        )
        return response.text
    except Exception as e:
        logger.error(f"Gemini Error: {e}")
        return "I am having trouble contemplating right now, Please try again in a moment"


async def safe_admin_alert(bot, admin_id, text):
    """
    Send an admin alert with retry logic for robustness.

    Tries up to 3 times with exponential backoff-like delays.

    Parameters
    ----------
    bot : telegram.Bot
        The bot instance used to send the message.
    admin_id : int
        The admin chat ID.
    text : str
        The alert message content.

    Returns
    -------
    bool
        True if the alert was sent successfully, False otherwise.
    """
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


# Telegram handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_message = (
        f"👋 Hello {user.first_name}!\n\n"
        "I’m a spiritual companion bot. "
        "Send me any message and I’ll reply thoughtfully.\n\n"
        "I can help find scripture or pray with you. I am an AI, not a priest."
    )
    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_message = (
        "📖 *Bot Help*\n\n"
        "Here’s what I can do:\n"
        "• I can help find scripture or pray with you\n"
        "• Crisis safety check: if I detect distress, I’ll respond with supportive guidance\n"
        "• Admin alert: I notify the owner if a crisis is flagged\n\n"
        "Commands:\n"
        "• /start – Welcome message\n"
        "• /help – Show this help menu\n\n"
        "Just type any message and I’ll reply!"
    )
    await update.message.reply_text(help_message, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    # Show typing action while waiting for AI
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Log user input (async-safe)
    await log_securely(user_id, "USER", user_text)

    # Get AI response
    ai_reply = await get_gemini_response(user_text)

    # Check for None response (error handler)
    if not ai_reply:
        ai_reply = "I am currently unavailable."

    # Safety check
    if "FLAG:CRISIS" in ai_reply:
        final_reply = (
            "I hear deep pain in your words. Please, you are valuable.\n\n"
            "📌 Contact your Priest(680727236)https://t.me/defpatrick or call emergency services immediately."
        )
        # Only notify admin if ID is set and valid
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

    # Reply and log
    await update.message.reply_text(final_reply)
    await log_securely(user_id, "BOT", final_reply)


def main():
    """
    Synchronous entrypoint:
    - Set Windows selector event loop policy (avoids Proactor issues).
    - Create and set a current event loop in MainThread (PTB expects one).
    - Run async DB init on that loop.
    - Start health server thread.
    - Run telegram polling (blocking).
    """
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
        #  Cleanup health server after polling stops
        stop_health_server()
        try:
            loop.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
