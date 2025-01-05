# Оптимизированная версия кода
import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import aiosqlite
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# Load environment variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', 0))
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL', '').rstrip('/') + WEBHOOK_PATH
G_SHEET_KEY = json.loads(os.getenv('G_SHEET_KEY', '{}'))

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_FILE = 'messages.db'

async def init_db():
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                user_id INTEGER, 
                username TEXT, 
                chat_id INTEGER, 
                chat_title TEXT, 
                message_count INTEGER,
                PRIMARY KEY (user_id, chat_id)
            )
        ''')
        await conn.commit()

# Initialize database
asyncio.run(init_db())

# Google Sheets setup
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
try:
    creds = ServiceAccountCredentials.from_json_keyfile_dict(G_SHEET_KEY, scope)
    client = gspread.authorize(creds)
except Exception as e:
    client = None
    print(f"Google Sheets setup failed: {e}")

@dp.message(Command('start'))
async def start_command(message: types.Message):
    await message.reply("Привет! Я считаю сообщения и показываю статистику.\nКоманды:\n/start\n/count\n/mystats\n/import")

@dp.message(Command('count'))
async def count_messages(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.reply("Доступ запрещён.")
        return

    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.execute('''
            SELECT chat_title, COUNT(DISTINCT user_id), SUM(message_count)
            FROM messages GROUP BY chat_id ORDER BY SUM(message_count) DESC
        ''')
        chat_stats = await cursor.fetchall()

    if not chat_stats:
        await message.reply("Нет данных.")
    else:
        report = "Групповая статистика:\n\n" + "\n".join(
            f"Группа: {chat}\nПользователи: {users}\nСообщения: {messages}" for chat, users, messages in chat_stats
        )
        await message.reply(report)

@dp.message(Command('mystats'))
async def my_stats(message: types.Message):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.execute('''
            SELECT chat_title, message_count FROM messages WHERE user_id = ? ORDER BY message_count DESC
        ''', (user_id,))
        user_stats = await cursor.fetchall()

    if not user_stats:
        await message.reply("Нет статистики.")
    else:
        report = f"Статистика @{message.from_user.username or 'unknown'}:\n\n" + "\n".join(
            f"Группа: {chat}\nСообщения: {messages}" for chat, messages in user_stats
        )
        await message.reply(report)

@dp.message(Command('import'))
async def import_to_sheets(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.reply("Доступ запрещён.")
        return

    if not client:
        await message.reply("Интеграция с Google Sheets не настроена.")
        return

    try:
        sheet = client.open('TelegramBotStats').sheet1
        async with aiosqlite.connect(DB_FILE) as conn:
            cursor = await conn.execute('SELECT chat_id, chat_title FROM messages GROUP BY chat_id')
            chats = await cursor.fetchall()

            for chat_id, chat_title in chats:
                try:
                    worksheet = sheet.worksheet(chat_title)
                except gspread.WorksheetNotFound:
                    worksheet = sheet.add_worksheet(title=chat_title, rows="1000", cols="4")
                
                headers = ['User ID', 'Username', 'Messages']
                worksheet.update('A1:C1', [headers])

                cursor = await conn.execute('''
                    SELECT user_id, username, message_count FROM messages WHERE chat_id = ? ORDER BY message_count DESC
                ''', (chat_id,))
                rows = await cursor.fetchall()

                worksheet.update('A2', rows)
        await message.reply("Данные успешно экспортированы.")
    except Exception as e:
        await message.reply(f"Ошибка при экспорте: {e}")

@dp.message()
async def count_message(message: types.Message):
    async with aiosqlite.connect(DB_FILE) as conn:
        await conn.execute('''
            INSERT OR REPLACE INTO messages (user_id, username, chat_id, chat_title, message_count)
            VALUES (?, ?, ?, ?, COALESCE((SELECT message_count FROM messages WHERE user_id = ? AND chat_id = ?), 0) + 1)
        ''', (message.from_user.id, message.from_user.username or "Unknown", message.chat.id, message.chat.title or "Unknown", message.from_user.id, message.chat.id))
        await conn.commit()

async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown(bot: Bot):
    await bot.delete_webhook()

def main():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(lambda _: asyncio.create_task(on_startup(bot)))
    app.on_shutdown.append(lambda _: asyncio.create_task(on_shutdown(bot)))

    port = int(os.getenv('PORT', 8080))
    web.run_app(app, host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()
