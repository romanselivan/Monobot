import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import sqlite3

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID'))
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST')
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация базы данных
conn = sqlite3.connect('messages.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS messages
                  (user_id INTEGER, username TEXT, message_count INTEGER)''')
conn.commit()

@dp.message(Command('count'))
async def count_messages(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        return

    cursor.execute('SELECT username, message_count FROM messages ORDER BY message_count DESC')
    user_messages = cursor.fetchall()
    
    report = "Количество сообщений пользователей:\n\n"
    for username, count in user_messages:
        report += f"@{username}: {count}\n"
    
    await message.reply(report)

@dp.message()
async def count_message(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    cursor.execute('''INSERT OR REPLACE INTO messages (user_id, username, message_count)
                      VALUES (?, ?, COALESCE((SELECT message_count FROM messages WHERE user_id = ?), 0) + 1)''',
                   (user_id, username, user_id))
    conn.commit()

async def on_startup(bot: Bot) -> None:
    await bot.set_webhook(WEBHOOK_URL)

def main():
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    web.run_app(app, host="0.0.0.0", port=8080)

if __name__ == '__main__':
    main()