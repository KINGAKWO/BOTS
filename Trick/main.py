import os
import logging
import sqlite3
from datetime import datetime
import google.generativeai as genai
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes, ApplicationBuilder
from cryptography.fernet import Fernet


# Bot identity
BOT_USERNAME = "@BiblicalCounselorBot"

# Load environment variables
load_dotenv()
Token = os.getenv("BOT_TOKEN")
API = os.getenv("API_KEY")
ENCRYPTION = os.getenv("ENCRYPTION_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Check for missing keys
if not all([Token, API, ENCRYPTION]):
    raise ValueError("Missing Keys in .env file!")

# Configure Gemini and encryption
genai.configure(api_key=API)
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

# Gemini system instruction
SYSTEM_INSTRUCTION = """
You are a warm, wise Catholic spiritual companion.
1. DOCTRINE: Use the RSV-CE Bible. Stick to the Catechism (CCC).
2. TONE: Compassionate, like a wise elder. Not robotic.
3. SAFETY PROTOCOL:
   - If user indicates SELF-HARM, SUICIDE, or ABUSE:
   - Output ONLY this exact string: "FLAG:CRISIS"
   - Do not output spiritual advice in that specific case.
"""

# Gemini response function
async def get_gemini_response(user_text):
    try:
        model = genai.GenerativeModel("gemini-pro")
        response = await model.generate_content_async(
            [SYSTEM_INSTRUCTION, user_text],
            generation_config={"temperature": 0.7, "max_output_tokens": 400}
        )
        if hasattr(response, "text"):
            return response.text
        else:
            logger.error("Gemini response missing 'text'")
            return "I am having trouble contemplating right now, Please try again in a moment"
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

    # Show typing
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Log user input
    log_securely(user_id, "USER", user_text)

    # Get AI response
    ai_reply = await get_gemini_response(user_text)

    # Safety check
    if "FLAG:CRISIS" in ai_reply:
        final_reply = (
            "I hear deep pain in your words. Please, you are valuable.\n\n"
            "📌 Contact your Priest or call emergency services immediately."
        )
        if ADMIN_ID != 0:
            alert_message = (
                f"⚠️ Crisis detected!\n\n"
                f"👤 User ID: {user_id}\n"
                f"📝 Message: {user_text}\n"
                f"🤖 AI Reply: {ai_reply}"
            )
            await context.bot.send_message(chat_id=ADMIN_ID, text=alert_message)
    else:
        final_reply = ai_reply

    # Reply and log
    await update.message.reply_text(final_reply)
    log_securely(user_id, "BOT", final_reply)

# Entry point
if __name__ == '__main__':
    init_db()
    application = ApplicationBuilder().token(Token).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("Bot is running...")
    application.run_polling()