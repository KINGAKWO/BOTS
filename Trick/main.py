import os
import logging
import asyncio
import sqlite3
from datetime import datetime
from google import genai
from dotenv import load_dotenv

# third party libraries
from telegram import Update, ForceReply
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
# from openai import AsyncOpenAI
from cryptography.fernet import Fernet

BOT_USERNAME = "@BiblicalCounselorBot"
load_dotenv()
Token = os.getenv("BOT_TOKEN")
API = os.getenv("API_KEY")
ENCRYPTION = os.getenv("ENCRYPTION_KEY")

if not all(Token, API, ENCRYPTION):
    raise ValueError("Missing Keys in .env file!")

client = genai.Client(api_keys="API")
cipher = Fernet(ENCRYPTION.encode())

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database Functions(SQLite)
DB_FILE = 'ministry.db'


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # logs table
    c.execute('''CREATE TABLE IF NOT EXISTS logs
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        timestamp TEXT,
        sender TEXT,
        encrypted_content TEXT''')
    conn.commit()
    conn.close()


def log_securely(user_id, sender_type, text):
    """Encrypts text and saves to DB"""
    try:
        encrypted_blob = cipher.encrypt(text.encode().decode()).decode()
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO logs(user_id, timestamp, sender, encrypted_connect)VALUES(?,?,?,?)",
                  (user_id, datetime.now().isoformat(),sender_type,encrypted_blob))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Logging failed: {e}")



