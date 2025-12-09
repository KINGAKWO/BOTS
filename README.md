#Lewis: Catholic Spiritual Companion Bot ✝️🤖
A Telegram chatbot named "Lewis" designed to provide spiritual comfort, biblical encouragement, and pastoral listening using AI, while maintaining strict safety guardrails and user privacy.

Note: This bot is NOT a replacement for a priest, psychologist, or medical professional. It is a supportive companion with built-in crisis protocols.

✨ Key Features
🤖 AI-Powered Spiritual Companion: Uses OpenRouter API with a fallback chain for reliability.

Primary Model: google/gemini-2.0-flash-exp:free

Fallback Model: amazon/nova-2-lite-v1:free

System prompt is tuned for compassionate, doctrine-aware (Catholic/RSV-CE Bible) responses.

🛡️ Proactive Safety & Crisis Protocol: Implements a real-time safety filter.

If a user's message indicates self-harm, suicide, or abuse, the AI's standard response is overridden.

The bot outputs a specific flag (FLAG:CRISIS) and immediately provides supportive guidance and emergency contacts to the user.

Simultaneously, an alert is sent to a designated human admin for potential follow-up.

🔒 End-to-End Conversation Privacy: All chat logs are encrypted at rest using Fernet (symmetric) encryption before being stored in a local SQLite database. Even with database access, conversations cannot be read without the unique encryption key.

💰 Cost-Optimized & Reliable: Designed to run 24/7 for less than $1/month.

Hosted on Render's Free Tier.

Uses a lightweight health-check server to stay active.

Implements request throttling and intelligent model fallback to maximize uptime.

🛠️ Tech Stack
Language: Python 3.11+

Bot Framework: python-telegram-bot (Async)

AI Provider & Models: OpenRouter API (Gemini 2.0 Flash Experimental, Nova 2 Lite)

Security: cryptography (Fernet)

Database: aiosqlite (Async SQLite)

Deployment: Render (Web Service)

🚀 Local Setup & Installation
Clone the repository

bash
git clone https://github.com/KINGAKWO/BOTS.git
cd BOTS/Trick  # Navigate to the project directory
Create and activate a virtual environment

bash
python -m venv venv
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
Install dependencies

bash
pip install -r requirements.txt
Configure your environment variables
Create a .env file in the project's root directory.

First, generate a secure encryption key:

bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
Copy the output. Now create your .env file with the following variables (use the key you just generated):

env
# Required
BOT_TOKEN=your_telegram_bot_token_from_BotFather
OPENROUTER_API_KEY=your_key_from_openrouter.ai
ENCRYPTION_KEY=the_generated_fernet_key_here

# Optional (Set to 0 to disable)
ADMIN_ID=your_telegram_user_id_for_crisis_alerts
Run the bot

bash
python main.py
☁️ Deployment on Render
This bot is configured for easy deployment on Render's free tier.

Push this code to a GitHub repository.

On Render, create a new Web Service.

Connect your GitHub repository.

Configure the service:

Build Command: pip install -r requirements.txt

Start Command: python main.py

In the Render dashboard, go to the Environment section and add all the environment variables from your .env file (BOT_TOKEN, OPENROUTER_API_KEY, etc.).

Click "Create Web Service". The built-in health check server will satisfy Render's requirement for a web server.

Tip for 24/7 Uptime: Render's free tier spins down after inactivity. To keep "Lewis" awake, you can use a monitoring service like UptimeRobot to ping your Render URL every 5 minutes.

⚠️ Important Disclaimer
This bot, "Lewis," is an Artificial Intelligence tool.

It is NOT the Sacrament of Reconciliation (Confession).

It is NOT a licensed therapist, counselor, or medical doctor.

It is NOT a replacement for professional human care, spiritual direction, or emergency services.

The bot includes explicit safety protocols to direct users in crisis to immediate human help. Users are informed of its nature and limitations upon first interaction.

🤝 Contributing
Contributions, ideas, and feedback are welcome! Please feel free to submit issues or pull requests.

Fork the Project

Create your Feature Branch (git checkout -b feature/AmazingFeature)

Commit your Changes (git commit -m 'Add some AmazingFeature')

Push to the Branch (git push origin feature/AmazingFeature)

Open a Pull Request

📄 License
Distributed under the MIT License. See the LICENSE file for more information.

Let me know if you'd like to add a visual diagram of the bot's architecture or a more detailed "How It Works" flowchart to the README!

This response is AI-generated, for reference only.
