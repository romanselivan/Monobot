import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import sqlite3
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load configuration from environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', 0))
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL', '') + WEBHOOK_PATH
G_SHEET_KEY = json.loads(os.getenv('G_SHEET_KEY', '{}'))

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Initialize database
def init_db():
    with sqlite3.connect('messages.db') as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS messages (
                        user_id INTEGER, 
                        username TEXT, 
                        chat_id INTEGER, 
                        chat_title TEXT, 
                        message_count INTEGER,
                        PRIMARY KEY (user_id, chat_id))''')
init_db()

# Google Sheets setup
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
client = None
try:
    creds = ServiceAccountCredentials.from_json_keyfile_dict(G_SHEET_KEY, scope)
    client = gspread.authorize(creds)
except Exception as e:
    logger.error(f"Failed to initialize Google Sheets client: {e}")

async def periodic_save():
    while True:
        try:
            await asyncio.sleep(300)  # Save every 5 minutes
            with sqlite3.connect('messages.db') as conn:
                conn.commit()
        except Exception as e:
            logger.error(f"Error during periodic save: {e}")

@dp.message(Command('count'))
async def count_messages(message: types.Message):
    try:
        if message.from_user.id != ADMIN_USER_ID:
            await message.reply("Access denied.")
            return

        with sqlite3.connect('messages.db') as conn:
            cursor = conn.execute('''
                SELECT chat_title, COUNT(DISTINCT user_id) as user_count, SUM(message_count) as total_messages
                FROM messages
                GROUP BY chat_id
                ORDER BY total_messages DESC
            ''')
            chat_stats = cursor.fetchall()

        if not chat_stats:
            await message.reply("No data available.")
            return

        report = "Group statistics:\n\n"
        for chat_title, user_count, total_messages in chat_stats:
            report += f"Group: {chat_title}\nUsers: {user_count}\nMessages: {total_messages}\n\n"
        await message.reply(report)

    except Exception as e:
        logger.error(f"Error in /count command: {e}")
        await message.reply("An error occurred while processing your request.")

@dp.message(Command('start'))
async def start(message: types.Message):
    try:
        text = (
            "I help my friends exchange one thing for another. Here are some commands you can use:\n"
            "/count - View the stats of all groups\n"
            "/mystats - View your personal stats\n"
            "/import - Export data to Google Sheets"
        )
        await message.reply(text)
    except Exception as e:
        logger.error(f"Error in /start command: {e}")
        await message.reply("An error occurred while processing your request.")

@dp.message()
async def count_message(message: types.Message):
    try:
        user_id = message.from_user.id
        username = message.from_user.username or "Unknown"
        chat_id = message.chat.id
        chat_title = message.chat.title or "Unknown"

        with sqlite3.connect('messages.db') as conn:
            conn.execute('''
                INSERT OR REPLACE INTO messages (user_id, username, chat_id, chat_title, message_count)
                VALUES (?, ?, ?, ?, COALESCE((SELECT message_count FROM messages WHERE user_id = ? AND chat_id = ?), 0) + 1)
            ''', (user_id, username, chat_id, chat_title, user_id, chat_id))

    except Exception as e:
        logger.error(f"Error in message counting: {e}")

async def on_startup(bot: Bot):
    try:
        await bot.set_webhook(WEBHOOK_URL)
        asyncio.create_task(periodic_save())
    except Exception as e:
        logger.error(f"Error during startup: {e}")

async def on_shutdown(bot: Bot):
    try:
        await bot.delete_webhook()
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

# Main application setup
def main():
    try:
        app = web.Application()
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)

        app.on_startup.append(lambda app: asyncio.create_task(on_startup(bot)))
        app.on_shutdown.append(lambda app: asyncio.create_task(on_shutdown(bot)))

        port = int(os.getenv('PORT', 10000))
        web.run_app(app, host='0.0.0.0', port=port)

    except Exception as e:
        logger.error(f"Error during main execution: {e}")

if __name__ == '__main__':
    main()
