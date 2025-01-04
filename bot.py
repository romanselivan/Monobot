import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import sqlite3
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

# Загрузка конфигурации из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', 0))
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL', '') + WEBHOOK_PATH
G_SHEET_KEY = json.loads(os.getenv('G_SHEET_KEY', '{}'))

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация базы данных
conn = sqlite3.connect('messages.db', isolation_level=None, check_same_thread=False)
cursor = conn.cursor()

# Создание таблицы, если она не существует, и добавление недостающих колонок
cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        user_id INTEGER,
        username TEXT,
        chat_id INTEGER,
        chat_title TEXT,
        message_count INTEGER,
        PRIMARY KEY (user_id, chat_id)
    )
''')
# Добавление колонок, если они отсутствуют
columns_to_check = ['chat_title']
for column in columns_to_check:
    try:
        cursor.execute(f"SELECT {column} FROM messages LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute(f"ALTER TABLE messages ADD COLUMN {column} TEXT")

# Настройка доступа к Google Sheets
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_dict(G_SHEET_KEY, scope)
client = gspread.authorize(creds)

async def periodic_save():
    """Сохранение изменений в базе данных каждые 5 минут."""
    while True:
        await asyncio.sleep(300)  # 5 минут
        conn.commit()

async def keep_alive():
    """Поддержка активности сервиса."""
    while True:
        await asyncio.sleep(840)  # 14 минут
        print("Service is alive")

@dp.message(Command('count'))
async def count_messages(message: types.Message):
    """Команда для отображения статистики по группам (доступна только администратору)."""
    if message.from_user.id != ADMIN_USER_ID:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    cursor.execute('''
        SELECT chat_title, COUNT(DISTINCT user_id) as user_count, SUM(message_count) as total_messages
        FROM messages
        GROUP BY chat_id
        ORDER BY total_messages DESC
    ''')
    chat_stats = cursor.fetchall()

    if not chat_stats:
        await message.reply("Статистика отсутствует.")
        return

    report = "Статистика по группам:\n\n"
    for chat_title, user_count, total_messages in chat_stats:
        report += f"Группа: {chat_title or 'Без названия'}\n"
        report += f"Пользователей: {user_count}\n"
        report += f"Всего сообщений: {total_messages}\n\n"

    await message.reply(report)

@dp.message(Command('mystats'))
async def my_stats(message: types.Message):
    """Команда для отображения статистики пользователя."""
    user_id = message.from_user.id
    username = message.from_user.username or "Без имени"

    cursor.execute('''
        SELECT chat_title, message_count
        FROM messages
        WHERE user_id = ?
        ORDER BY message_count DESC
    ''', (user_id,))
    user_stats = cursor.fetchall()

    if not user_stats:
        await message.reply("У вас пока нет статистики.")
        return

    report = f"Ваша статистика, @{username}:\n\n"
    for chat_title, message_count in user_stats:
        report += f"Группа: {chat_title or 'Без названия'}\n"
        report += f"Сообщений: {message_count}\n\n"

    await message.reply(report)

@dp.message(Command('import'))
async def import_to_sheets(message: types.Message):
    """Выгрузка данных в Google Sheets (доступна только администратору)."""
    if message.from_user.id != ADMIN_USER_ID:
        await message.reply("У вас нет прав для выполнения этой команды.")
        return

    await message.reply("Начинаю выгрузку данных в Google Sheets...")

    try:
        sheet = client.open('TelegramBotStats').sheet1

        cursor.execute('SELECT DISTINCT chat_id, chat_title FROM messages')
        chats = cursor.fetchall()

        for chat_id, chat_title in chats:
            try:
                worksheet = sheet.worksheet(chat_title or f"Chat {chat_id}")
            except gspread.WorksheetNotFound:
                worksheet = sheet.add_worksheet(title=chat_title or f"Chat {chat_id}", rows="1000", cols="20")

            headers = ['User ID', 'Username', 'Message Count', 'Last Updated']
            worksheet.update('A1:D1', [headers])

            cursor.execute('''
                SELECT user_id, username, message_count
                FROM messages
                WHERE chat_id = ?
                ORDER BY message_count DESC
            ''', (chat_id,))
            data = cursor.fetchall()

            current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data_with_date = [list(row) + [current_date] for row in data]

            worksheet.update('A2', data_with_date)

        await message.reply("Данные успешно выгружены в Google Sheets.")
    except Exception as e:
        await message.reply(f"Ошибка при выгрузке данных: {str(e)}")

@dp.message()
async def count_message(message: types.Message):
    """Отслеживание сообщений пользователей."""
    user_id = message.from_user.id
    username = message.from_user.username or "Без имени"
    chat_id = message.chat.id
    chat_title = message.chat.title or "Без названия"

    cursor.execute('''
        INSERT OR REPLACE INTO messages (user_id, username, chat_id, chat_title, message_count)
        VALUES (?, ?, ?, ?, COALESCE((SELECT message_count FROM messages WHERE user_id = ? AND chat_id = ?), 0) + 1)
    ''', (user_id, username, chat_id, chat_title, user_id, chat_id))

async def on_startup(bot: Bot):
    """Действия при запуске бота."""
    await bot.set_webhook(WEBHOOK_URL)
    asyncio.create_task(periodic_save())
    asyncio.create_task(keep_alive())

async def on_shutdown(bot: Bot):
    """Действия при остановке бота."""
    await bot.delete_webhook()
    conn.close()

def main():
    """Запуск веб-сервера."""
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(lambda app: asyncio.create_task(on_startup(bot)))
    app.on_shutdown.append(lambda app: asyncio.create_task(on_shutdown(bot)))

    port = int(os.getenv('PORT', 10000))
    web.run_app(app, host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()
