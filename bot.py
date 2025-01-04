import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import sqlite3
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

# Load configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', 0))
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL', '') + WEBHOOK_PATH
G_SHEET_KEY = json.loads(os.getenv('G_SHEET_KEY', '{}'))

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Google Sheets setup
def init_google_sheets():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(G_SHEET_KEY, scope)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"Failed to initialize Google Sheets client: {e}")
        return None

client = init_google_sheets()

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

# Database operations
def execute_db(query, params=()):
    with sqlite3.connect('messages.db') as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

async def periodic_save():
    while True:
        await asyncio.sleep(300)  # Save every 5 minutes
        with sqlite3.connect('messages.db') as conn:
            conn.commit()

# Commands
@dp.message(Command('start'))
async def start(message: types.Message):
    start_text = (
        "Привет! Я помогу тебе отслеживать статистику сообщений в группах.\n\n"
        "Вот что я умею:\n"
        "/count — Показать статистику по группам (пользователи, сообщения).\n"
        "/mystats — Показать твою статистику по группам.\n"
        "/import — Экспортировать данные в Google Sheets.\n\n"
        "Просто напиши что-нибудь в чате, и я буду отслеживать твои сообщения!"
    )
    await message.reply(start_text)

@dp.message(Command('count'))
async def count_messages(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.reply("Access denied.")
        return

    stats = execute_db('''
        SELECT chat_title, COUNT(DISTINCT user_id) as user_count, SUM(message_count) as total_messages
        FROM messages
        GROUP BY chat_id
        ORDER BY total_messages DESC
    ''')
    if not stats:
        await message.reply("No data available.")
        return

    report = "Group statistics:\n\n" + "\n".join(
        [f"Group: {chat_title}\nUsers: {user_count}\nMessages: {total_messages}" 
         for chat_title, user_count, total_messages in stats]
    )
    await message.reply(report)

@dp.message(Command('mystats'))
async def my_stats(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"

    user_stats = execute_db('''
        SELECT chat_title, message_count
        FROM messages
        WHERE user_id = ?
        ORDER BY message_count DESC
    ''', (user_id,))

    if not user_stats:
        await message.reply("You have no statistics yet.")
        return

    report = f"Your statistics, @{username}:\n\n" + "\n".join(
        [f"Group: {chat_title}\nMessages: {message_count}" 
         for chat_title, message_count in user_stats]
    )
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
        chats = execute_db('SELECT DISTINCT chat_id, chat_title FROM messages')
        
        for chat_id, chat_title in chats:
            worksheet = sheet.add_worksheet(title=chat_title, rows="1000", cols="20") if not sheet.worksheet(chat_title) else sheet.worksheet(chat_title)

            headers = ['User ID', 'Username', 'Message Count', 'Last Updated']
            worksheet.update('A1:D1', [headers])

            user_data = execute_db('''
                SELECT user_id, username, message_count
                FROM messages
                WHERE chat_id = ?
                ORDER BY message_count DESC
            ''', (chat_id,))
            current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data_with_date = [list(row) + [current_date] for row in user_data]
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

    execute_db('''
        INSERT OR REPLACE INTO messages (user_id, username, chat_id, chat_title, message_count)
        VALUES (?, ?, ?, ?, COALESCE((SELECT message_count FROM messages WHERE user_id = ? AND chat_id = ?), 0) + 1)
    ''', (user_id, username, chat_id, chat_title, user_id, chat_id))

async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)
    asyncio.create_task(periodic_save())

async def on_shutdown(bot: Bot):
    await bot.delete_webhook()

# Main app setup
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
