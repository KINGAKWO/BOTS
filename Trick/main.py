import logging
import os
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes, ApplicationBuilder


# Hosting.......................................................................................
# this class creates a dummy web server so Render doesn't kill the bot
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def start_health_server():
 # Render assigns the port via the PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f"Health check server listening on port {port}")
    server.serve_forever()
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


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        timestamp TEXT,
        sender TEXT,
        encrypted_content TEXT
    )''')
    conn.commit()
    conn.close()


def log_securely(user_id, sender_type, text):
    try:
        encrypted_blob = cipher.encrypt(text.encode()).decode()
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO logs(user_id, timestamp, sender, encrypted_content) VALUES (?,?,?,?)",
                  (user_id, datetime.now().isoformat(), sender_type, encrypted_blob))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Logging failed: {e}")


# Gemini response function
async def get_gemini_response(user_text):
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

        # Removed the stray chat/file/tuning creation calls that were here.
        # They should not be called every time a user sends a message.

        return response.text
    except Exception as e:
        logger.error(f"Gemini Error: {e}")
        return "I am having trouble contemplating right now, Please try again in a moment"


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
        "• Answer questions and explain concepts using Gemini AI\n"
        "• Summarize text or generate creative writing\n"
        "• Provide coding explanations and study support\n"
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

    # Log user input
    log_securely(user_id, "USER", user_text)

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
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=alert_message)
            except Exception as e:
                logger.error(f"Failed to alert admin: {e}")
    else:
        final_reply = ai_reply

    # Reply and log
    await update.message.reply_text(final_reply)
    log_securely(user_id, "BOT", final_reply)


# Entry point
if __name__ == '__main__':
    # starting dummy web server
    threading.Thread(target=start_health_server, daemon=True).start()

    # Bot logic
    init_db()
    application = ApplicationBuilder().token(Token).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # start polling
    print("Bot is running...")
    application.run_polling()