import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import sqlite3
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# Load configuration from environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', 0))
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL', '') + WEBHOOK_PATH
G_SHEET_KEY = json.loads(os.getenv('G_SHEET_KEY', '{}'))

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Database initialization with optional reset
DB_FILE = 'messages.db'
if os.getenv('RESET_DB', 'false').lower() == 'true':
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
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
try:
    creds = ServiceAccountCredentials.from_json_keyfile_dict(G_SHEET_KEY, scope)
    client = gspread.authorize(creds)
except Exception as e:
    client = None
    print(f"Failed to initialize Google Sheets client: {e}")

# Commands
@dp.message(Command('start'))
async def start_command(message: types.Message):
    commands = """
    Welcome! Here are my commands:
    /start - Show this help message
    /count - Show group statistics (admin only)
    /mystats - Show your message stats
    /import - Export stats to Google Sheets (admin only)
    """
    await message.reply(commands)

@dp.message(Command('count'))
async def count_messages(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.reply("Access denied.")
        return

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.execute('''
                SELECT chat_title, COUNT(DISTINCT user_id) AS user_count, SUM(message_count) AS total_messages
                FROM messages
                GROUP BY chat_id
                ORDER BY total_messages DESC
            ''')
            chat_stats = cursor.fetchall()
    except sqlite3.Error as e:
        await message.reply(f"Database error: {e}")
        return

    if not chat_stats:
        await message.reply("No data available.")
        return

    report = "Group statistics:\n\n"
    for chat_title, user_count, total_messages in chat_stats:
        report += f"Group: {chat_title}\nUsers: {user_count}\nMessages: {total_messages}\n\n"
    await message.reply(report)

@dp.message(Command('mystats'))
async def my_stats(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.execute('''
                SELECT chat_title, message_count
                FROM messages
                WHERE user_id = ?
                ORDER BY message_count DESC
            ''', (user_id,))
            user_stats = cursor.fetchall()
    except sqlite3.Error as e:
        await message.reply(f"Database error: {e}")
        return

    if not user_stats:
        await message.reply("You have no statistics yet.")
        return

    report = f"Your statistics, @{username}:\n\n"
    for chat_title, message_count in user_stats:
        report += f"Group: {chat_title}\nMessages: {message_count}\n\n"
    await message.reply(report)

@dp.message(Command('import'))
async def import_to_sheets(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.reply("Access denied.")
        return

    if not client:
        await message.reply("Google Sheets integration is not configured.")
        return

    await message.reply("Exporting data to Google Sheets...")

    try:
        sheet = client.open('TelegramBotStats').sheet1

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.execute('SELECT DISTINCT chat_id, chat_title FROM messages')
            chats = cursor.fetchall()

            for chat_id, chat_title in chats:
                try:
                    worksheet = sheet.worksheet(chat_title)
                except gspread.WorksheetNotFound:
                    worksheet = sheet.add_worksheet(title=chat_title, rows="1000", cols="20")

                headers = ['User ID', 'Username', 'Message Count', 'Last Updated']
                worksheet.update('A1:D1', [headers])

                cursor = conn.execute('''
                    SELECT user_id, username, message_count
                    FROM messages
                    WHERE chat_id = ?
                    ORDER BY message_count DESC
                ''', (chat_id,))
                data = cursor.fetchall()

                current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                data_with_date = [list(row) + [current_date] for row in data]

                worksheet.update('A2', data_with_date)

        await message.reply("Data exported successfully.")
    except Exception as e:
        await message.reply(f"Error during export: {e}")

@dp.message()
async def count_message(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"
    chat_id = message.chat.id
    chat_title = message.chat.title or "Unknown"

    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO messages (user_id, username, chat_id, chat_title, message_count)
                VALUES (?, ?, ?, ?, COALESCE((SELECT message_count FROM messages WHERE user_id = ? AND chat_id = ?), 0) + 1)
            ''', (user_id, username, chat_id, chat_title, user_id, chat_id))
    except sqlite3.Error as e:
        print(f"Error in message counting: {e}")

async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown(bot: Bot):
    await bot.delete_webhook()

# Main application setup
def main():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(lambda app: asyncio.create_task(on_startup(bot)))
    app.on_shutdown.append(lambda app: asyncio.create_task(on_shutdown(bot)))

    port = int(os.getenv('PORT', 10000))
    web.run_app(app, host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()
