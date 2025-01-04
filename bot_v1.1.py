import os
import asyncio
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from pytoniq import LiteBalancer, WalletV3R2, Address, begin_cell
from tonsdk.contract.token.ft import JettonWallet

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
MY_TESTNET_WALLET_ADDRESS = os.getenv('MY_TESTNET_WALLET_ADDRESS')
TO_TESTNET_ADDRESS = os.getenv('TO_TESTNET_ADDRESS')
SECRET_PHRASE = os.getenv('SECRET_PHRASE').split()
MTY_TOKEN_ADDRESS = os.getenv('MTY_TOKEN_ADDRESS')

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

provider = None

keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/balance")],
        [KeyboardButton(text="/send")]
    ],
    resize_keyboard=True
)

async def get_wallet():
    global provider
    if provider is None:
        provider = LiteBalancer.from_testnet_config(1)
        await provider.start_up()
    
    wallet = await WalletV3R2.from_mnemonic(
        provider=provider,
        mnemonics=SECRET_PHRASE
    )
    return wallet

async def get_mty_balance(wallet_address):
    try:
        jetton_wallet = JettonWallet(Address(MTY_TOKEN_ADDRESS))
        balance = await jetton_wallet.get_wallet_data(provider, Address(wallet_address))
        return balance['balance']
    except Exception as e:
        logger.error(f"Error getting MTY balance: {e}")
        return 0

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    wallet = await get_wallet()
    wallet_address = wallet.address.to_str()
    await message.answer(f"Добро пожаловать! Адрес вашего кошелька: {wallet_address}\n\nВыберите команду:", reply_markup=keyboard)

@dp.message(Command("balance"))
async def cmd_balance(message: types.Message):
    try:
        wallet = await get_wallet()
        ton_balance = await wallet.get_balance()
        ton_balance_readable = ton_balance / 10**9

        mty_balance = await get_mty_balance(wallet.address.to_str())
        mty_balance_readable = mty_balance / 10**9

        wallet_address = wallet.address.to_str()
        tonscan_url = f"https://testnet.tonscan.org/address/{wallet_address}"

        await message.answer(
            f"Баланс вашего кошелька в тестовой сети TON:\n"
            f"TON: {ton_balance_readable:.9f}\n"
            f"MTY: {mty_balance_readable:.9f}\n"
            f"Адрес кошелька: <a href='{tonscan_url}'>{wallet_address}</a>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error in check_balance: {str(e)}", exc_info=True)
        await message.answer(f"Произошла ошибка при проверке баланса: {str(e)}")

@dp.message(Command("send"))
async def cmd_send(message: types.Message):
    try:
        wallet = await get_wallet()
        balance = await wallet.get_balance()
        
        if balance < 100000000:
            await message.answer(f"Недостаточно средств на кошельке. Текущий баланс: {balance / 10**9} TON")
            return

        transfer_amount = 10 * (10 ** 9)
        payload = begin_cell() \
            .store_uint(0xf8a7ea5, 32) \
            .store_uint(0, 64) \
            .store_coins(transfer_amount) \
            .store_address(Address(TO_TESTNET_ADDRESS)) \
            .store_address(None) \
            .store_coins(0) \
            .store_uint(0, 1) \
            .end_cell()

        tx = await wallet.transfer(
            destination=Address(MTY_TOKEN_ADDRESS),
            amount=100000000,
            body=payload
        )

        await message.answer(f"Транзакция на отправку 10 MTY успешно отправлена! Хэш: {tx.hash}")
    except Exception as e:
        logger.error(f"Error in send command: {str(e)}", exc_info=True)
        await message.answer(f"Произошла ошибка при отправке MTY: {str(e)}")

async def main():
    global provider
    try:
        await dp.start_polling(bot)
    finally:
        if provider:
            await provider.close_all()

if __name__ == '__main__':
    asyncio.run(main())