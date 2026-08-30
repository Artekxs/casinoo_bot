import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeDefault
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import DiceEmoji
import aiosqlite

from config import BOT_TOKEN, MIN_BET, MIN_WITHDRAW, MIN_DEPOSIT, CRYPTOBOT_TOKEN, ADMINS
from database import (
    init_db, get_or_create_user, get_user, update_balance,
    add_transaction, get_top_players,
    save_invoice, get_pending_invoices, update_invoice_status
)
from crypto_pay import CryptoBotPay

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

crypto_bot = CryptoBotPay(CRYPTOBOT_TOKEN) if CRYPTOBOT_TOKEN else None

active_games = {}
user_daily_bonus = {}
user_stats = {}

DB_PATH = "casino.db"

def get_game(user_id):
    return active_games.get(user_id)

def set_game(user_id, game_data):
    active_games[user_id] = game_data

def delete_game(user_id):
    if user_id in active_games:
        del active_games[user_id]

async def check_daily_bonus_available(user_id: int):
    today = datetime.now().date()
    if user_id in user_daily_bonus:
        if user_daily_bonus[user_id] == today:
            return False, "⏳ Вы уже получили ежедневный бонус сегодня!"
    
    stats = user_stats.get(user_id, {})
    total_deposits = stats.get('total_deposits', 0)
    games_played = stats.get('games_played', 0)
    
    if total_deposits < 1:
        return False, "❌ Нужно пополнить баланс хотя бы на <b>1$</b>"
    
    if games_played < 1:
        return False, "❌ Нужно сыграть хотя бы <b>1 игру</b>"
    
    return True, "✅ Можно забрать!"

async def has_welcome_bonus(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM transactions WHERE user_id = ? AND type = 'welcome'",
            (user_id,)
        ) as cursor:
            count = await cursor.fetchone()
            return count[0] > 0

async def mark_welcome_bonus_claimed(user_id: int):
    await add_transaction(user_id, 'welcome', 0.5, 'welcome', 'Приветственный бонус')

def main_menu_kb():
    kb = [
        [InlineKeyboardButton(text='🎮 Играть', callback_data='play'),
         InlineKeyboardButton(text='👤 Профиль', callback_data='profile')],
        [InlineKeyboardButton(text='💰 Кошелёк', callback_data='wallet'),
         InlineKeyboardButton(text='🏆 Топ', callback_data='top')],
        [InlineKeyboardButton(text='🎁 Бонусы', callback_data='bonus_menu'),
         InlineKeyboardButton(text='📜 История', callback_data='history_menu')],
        [InlineKeyboardButton(text='🆘 Поддержка', callback_data='support_menu'),
         InlineKeyboardButton(text='⚡ Быстрый вывод', callback_data='withdraw')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def games_kb():
    kb = [
        [InlineKeyboardButton(text='🎲 Куб (чёт/нечет)', callback_data='game_dice')],
        [InlineKeyboardButton(text='🎡 Рулетка', callback_data='game_roulette')],
        [InlineKeyboardButton(text='🪙 Орёл/Решка', callback_data='game_coinflip')],
        [InlineKeyboardButton(text='💣 Мины', callback_data='game_mines')],
        [InlineKeyboardButton(text='🗼 Башня', callback_data='game_tower')],
        [InlineKeyboardButton(text='◀️ Назад', callback_data='back_main')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def wallet_kb():
    kb = [
        [InlineKeyboardButton(text='⬇️ Пополнить', callback_data='deposit'),
         InlineKeyboardButton(text='⬆️ Вывести', callback_data='withdraw')],
        [InlineKeyboardButton(text='◀️ Назад', callback_data='back_main')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back_kb(callback='back_main'):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='◀️ Назад', callback_data=callback)]])

def bet_kb(game: str):
    kb = [
        [InlineKeyboardButton(text='0.5$', callback_data=f'bet_{game}_0.5'),
         InlineKeyboardButton(text='1$', callback_data=f'bet_{game}_1'),
         InlineKeyboardButton(text='2$', callback_data=f'bet_{game}_2')],
        [InlineKeyboardButton(text='5$', callback_data=f'bet_{game}_5'),
         InlineKeyboardButton(text='10$', callback_data=f'bet_{game}_10'),
         InlineKeyboardButton(text='25$', callback_data=f'bet_{game}_25')],
        [InlineKeyboardButton(text='✏️ Своя сумма', callback_data=f'bet_custom_{game}')],
        [InlineKeyboardButton(text='◀️ Назад', callback_data='play')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def dice_choice_kb(game: str, amount: float):
    kb = [
        [InlineKeyboardButton(text='🎲 ЧЁТ (x2)', callback_data=f'dice_even_{game}_{amount}')],
        [InlineKeyboardButton(text='🎲 НЕЧЕТ (x2)', callback_data=f'dice_odd_{game}_{amount}')],
        [InlineKeyboardButton(text='◀️ Назад', callback_data='play')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def roulette_bet_kb(game: str, amount: float):
    kb = [
        [InlineKeyboardButton(text='🔢 На число (x35)', callback_data=f'roulette_type_number_{game}_{amount}')],
        [InlineKeyboardButton(text='🎨 На цвет (x2)', callback_data=f'roulette_type_color_{game}_{amount}')],
        [InlineKeyboardButton(text='◀️ Назад', callback_data='play')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def roulette_number_kb(game: str, amount: float):
    kb = []
    row = []
    kb.append([InlineKeyboardButton(text='🟢 0', callback_data=f'roulette_num_0_{game}_{amount}')])
    for i in range(1, 37):
        if i in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]:
            color = '🔴'
        else:
            color = '⚫'
        row.append(InlineKeyboardButton(text=f'{color} {i}', callback_data=f'roulette_num_{i}_{game}_{amount}'))
        if len(row) == 6:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton(text='◀️ Назад', callback_data='play')])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def roulette_color_kb(game: str, amount: float):
    kb = [
        [InlineKeyboardButton(text='🔴 КРАСНОЕ (x2)', callback_data=f'roulette_color_red_{game}_{amount}')],
        [InlineKeyboardButton(text='⚫ ЧЁРНОЕ (x2)', callback_data=f'roulette_color_black_{game}_{amount}')],
        [InlineKeyboardButton(text='◀️ Назад', callback_data='play')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def coinflip_kb(game: str, amount: float):
    kb = [
        [InlineKeyboardButton(text='🦅 ОРЁЛ (x2)', callback_data=f'coinflip_eagle_{game}_{amount}')],
        [InlineKeyboardButton(text='🪙 РЕШКА (x2)', callback_data=f'coinflip_tails_{game}_{amount}')],
        [InlineKeyboardButton(text='◀️ Назад', callback_data='play')]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

class BetState(StatesGroup):
    waiting_custom_bet = State()
    waiting_withdraw = State()

@dp.callback_query(F.data == 'history_menu')
async def history_menu(callback: CallbackQuery):
    import aiosqlite
    from database import DB_PATH
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT type, amount, status, created_at FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 10",
            (callback.from_user.id,)
        ) as cursor:
            rows = await cursor.fetchall()
    
    if not rows:
        text = '📜 <b>История операций</b>\n\nПока нет ни одной операции.'
        await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode='HTML')
        await callback.answer()
        return
    
    text = '📜 <b>История операций (последние 10)</b>\n\n'
    emojis = {
        'deposit': '⬇️ Пополнение',
        'withdraw': '⬆️ Вывод',
        'game': '🎮 Игра',
        'bonus': '🎁 Бонус',
        'cashback': '🔄 Кешбэк',
        'deposit_bonus': '🎁 Бонус за пополнение',
        'welcome': '🎉 Приветственный'
    }
    for row in rows:
        name = emojis.get(row[0], row[0])
        status = '✅' if row[2] in ['done', 'completed', 'paid'] else '⏳'
        created = row[3][:16] if row[3] else ''
        text += f'{name} | {row[1]:.2f}$ | {status} {created}\n'
    
    await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data == 'support_menu')
async def support_menu(callback: CallbackQuery):
    text = (
        '🆘 <b>Поддержка</b>\n\n'
        '📌 <b>Мы ценим каждого игрока!</b>\n\n'
        '👑 <b>Поддержка:</b> @ASZ_Support\n'
        '⏰ Время ответа: до 24 часов\n'
        '💰 Вопросы по выводу: до 1 часа\n\n'
        '📋 <b>Правила вывода:</b>\n'
        '• Минимальная сумма: 2$\n'
        '• Вывод в течение 24 часов\n'
        '• Комиссия: 0%\n\n'
        '🔒 <b>Безопасность:</b>\n'
        '• Все транзакции защищены\n'
        '• Поддержка 24/7'
    )
    await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data == 'bonus_menu')
async def bonus_menu(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    
    import aiosqlite
    from database import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT SUM(amount) FROM transactions WHERE user_id = ? AND type = 'cashback'",
            (callback.from_user.id,)
        ) as cursor:
            cashback_row = await cursor.fetchone()
    real_cashback = cashback_row[0] if cashback_row[0] else 0
    
    me = await bot.get_me()
    bot_username = me.username
    ref_link = f'https://t.me/{bot_username}?start=ref_{user[0]}'
    
    available, msg = await check_daily_bonus_available(callback.from_user.id)
    
    stats = user_stats.get(callback.from_user.id, {})
    total_deposits = stats.get('total_deposits', 0)
    games_played = stats.get('games_played', 0)
    
    has_bonus = await has_welcome_bonus(callback.from_user.id)
    welcome_status = '✅ Получен' if has_bonus else '❌ Не получен'
    
    text = (
        f'🎁 <b>Бонусы и акции</b>\n\n'
        f'💰 Баланс: <b>{user[3]:.2f} $</b>\n\n'
        f'🎉 <b>Приветственный бонус:</b> 0.5$ — {welcome_status}\n'
        f'📈 <b>Бонус за пополнение:</b> +10% к сумме\n'
        f'🔄 <b>Кешбэк 5%:</b> {real_cashback:.2f} $\n'
        f'📅 <b>Ежедневный бонус:</b> 0.1$\n'
        f'   └ Пополнений: {total_deposits:.2f}$ | Игр: {games_played}\n'
        f'   └ {msg}\n\n'
        f'👥 <b>Реферальная программа:</b>\n'
        f'<code>{ref_link}</code>\n\n'
        f'💎 За каждого друга: <b>0.5$</b>\n\n'
        f'🏆 <b>Топ игроков получают дополнительные бонусы!</b>'
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📅 Забрать ежедневный бонус', callback_data='daily_bonus')],
        [InlineKeyboardButton(text='◀️ Назад', callback_data='back_main')]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data == 'daily_bonus')
async def daily_bonus(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    available, msg = await check_daily_bonus_available(user_id)
    if not available:
        await callback.answer(msg, show_alert=True)
        return
    
    await update_balance(user_id, 0.1)
    await add_transaction(user_id, 'bonus', 0.1, 'daily', 'Ежедневный бонус')
    user_daily_bonus[user_id] = datetime.now().date()
    
    user = await get_user(user_id)
    await callback.message.edit_text(
        f'✅ <b>Ежедневный бонус получен!</b>\n\n'
        f'💰 +0.1$ на баланс\n'
        f'Баланс: <b>{user[3]:.2f} $</b>\n\n'
        f'🎯 Возвращайтесь завтра!',
        reply_markup=back_kb(),
        parse_mode='HTML'
    )
    await callback.answer()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    ref_id = None
    if message.text and message.text.startswith('/start ref_'):
        try:
            ref_id = int(message.text.replace('/start ref_', ''))
        except:
            pass
    
    user = await get_or_create_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        referrer_id=ref_id
    )
    
    if not await has_welcome_bonus(message.from_user.id):
        await update_balance(message.from_user.id, 0.5)
        await mark_welcome_bonus_claimed(message.from_user.id)
        
        if ref_id:
            await update_balance(ref_id, 0.5)
            await add_transaction(ref_id, 'bonus', 0.5, 'referral', f'За приглашение {message.from_user.id}')
            try:
                await bot.send_message(
                    ref_id,
                    f'👥 По вашей ссылке зарегистрировался новый игрок!\n💰 Вы получили <b>0.5$</b>',
                    parse_mode='HTML'
                )
            except:
                pass
    
    if message.from_user.id not in user_stats:
        user_stats[message.from_user.id] = {'total_deposits': 0, 'games_played': 0}
    
    user = await get_user(message.from_user.id)
    text = (
        f'💎 <b>Добро пожаловать!</b>\n\n'
        f'🎁 Приветственный бонус: <b>0.5$</b>\n'
        f'💰 Баланс: <b>{user[3]:.2f} $</b>\n\n'
        f'🎯 Играй, выигрывай, выводи!'
    )
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode='HTML')

@dp.message(Command('menu'))
async def cmd_menu(message: Message):
    await cmd_start(message)

@dp.message(Command('games'))
async def cmd_games(message: Message):
    user = await get_user(message.from_user.id)
    text = (
        f'🎮 <b>Выберите игру</b>\n\n'
        f'💰 Баланс: <b>{user[3]:.2f} $</b>\n'
        f'Мин. ставка: <b>{MIN_BET} $</b>\n\n'
        f'🔥 <b>Самые популярные игры:</b>\n'
        f'• 🎡 Рулетка — x35 за число\n'
        f'• 🎲 Куб — x2 за чёт/нечет'
    )
    await message.answer(text, reply_markup=games_kb(), parse_mode='HTML')

@dp.message(Command('top'))
async def cmd_top(message: Message):
    top = await get_top_players(10)
    if not top:
        text = '🏆 Пока нет игроков в топе'
    else:
        text = '🏆 <b>Топ игроков по обороту</b>\n\n'
        for i, p in enumerate(top, 1):
            name = p[2] or p[1] or f'ID{p[0]}'
            text += f'{i}. {name} — <b>{p[3]:.2f} $</b>\n'
    await message.answer(text, parse_mode='HTML')

@dp.message(Command('withdraw'))
async def cmd_withdraw(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if user[3] < 2.0:
        await message.answer('❌ Минимальный вывод 2$')
        return
    
    if user[5] < 1.0:
        await message.answer('❌ Чтобы вывести средства, нужно пополнить баланс хотя бы на 1$')
        return
    
    await state.set_state(BetState.waiting_withdraw)
    await message.answer(
        f'⬆️ <b>Вывод средств</b>\n\n'
        f'💰 Баланс: <b>{user[3]:.2f} $</b>\n'
        f'📌 Мин. вывод: <b>2$</b>\n'
        f'📌 Условие: пополнение от 1$\n'
        f'⏱ Время вывода: до 24 часов\n'
        f'💳 Комиссия: 0%\n\n'
        f'Введите сумму для вывода:',
        parse_mode='HTML'
    )

@dp.message(Command('help'))
async def cmd_help(message: Message):
    text = (
        '❓ <b>Помощь</b>\n\n'
        '🔹 <code>/start</code> — Главное меню\n'
        '🔹 <code>/menu</code> — Главное меню\n'
        '🔹 <code>/games</code> — Список игр\n'
        '🔹 <code>/top</code> — Топ игроков\n'
        '🔹 <code>/deposit 10</code> — Пополнить баланс\n'
        '🔹 <code>/withdraw</code> — Вывод средств (мин. 2$, нужно пополнить 1$)\n\n'
        '🎮 <b>Игры:</b>\n'
        '• 🎲 Куб (чёт/нечет) — x2\n'
        '• 🎡 Рулетка — x35 (число) или x2 (цвет)\n'
        '• 🪙 Орёл/Решка — x2\n'
        '• 💣 Мины — множитель растёт\n'
        '• 🗼 Башня — множитель растёт\n\n'
        '🎁 <b>Бонусы:</b>\n'
        '• Приветственный: 0.5$ (только 1 раз)\n'
        '• Ежедневный: 0.1$ (пополни 1$ + сыграй 1 игру)\n'
        '• За пополнение: +10%\n'
        '• Кешбэк: 5% от проигрыша\n'
        '• Реферальный: 0.5$ за друга\n\n'
        '👑 <b>Админы:</b>\n'
        '• /withdraws — список заявок\n'
        '• /confirm_withdraw ID — подтвердить вывод\n'
        '• /addbalance ID сумма — начислить баланс'
    )
    await message.answer(text, parse_mode='HTML')

@dp.callback_query(F.data == 'back_main')
async def back_main(callback: CallbackQuery):
    delete_game(callback.from_user.id)
    user = await get_user(callback.from_user.id)
    text = (
        f'💎 <b>Добро пожаловать!</b>\n\n'
        f'💰 Баланс: <b>{user[3]:.2f} $</b>\n\n'
        f'🎯 Играй, выигрывай, выводи!'
    )
    await callback.message.edit_text(text, reply_markup=main_menu_kb(), parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data == 'play')
async def play_menu(callback: CallbackQuery):
    delete_game(callback.from_user.id)
    user = await get_user(callback.from_user.id)
    text = (
        f'🎮 <b>Выберите игру</b>\n\n'
        f'💰 Баланс: <b>{user[3]:.2f} $</b>\n'
        f'Мин. ставка: <b>{MIN_BET} $</b>\n\n'
        f'🔥 <b>Популярные игры:</b>\n'
        f'• 🎡 Рулетка — x35 за число\n'
        f'• 🎲 Куб — x2 за чёт/нечет'
    )
    await callback.message.edit_text(text, reply_markup=games_kb(), parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data == 'profile')
async def profile(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    reg_date = user[8] if user[8] else '—'
    
    import aiosqlite
    from database import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT SUM(amount) FROM transactions WHERE user_id = ? AND type = 'cashback'",
            (callback.from_user.id,)
        ) as cursor:
            cashback_row = await cursor.fetchone()
    real_cashback = cashback_row[0] if cashback_row[0] else 0
    
    stats = user_stats.get(callback.from_user.id, {})
    
    text = (
        f'👤 <b>Профиль</b>\n\n'
        f'Имя: <b>{user[2] or "—"}</b>\n'
        f'ID: <code>{user[0]}</code>\n'
        f'📅 Регистрация: {reg_date}\n\n'
        f'💰 Баланс: <b>{user[3]:.2f} $</b>\n'
        f'📊 Оборот: <b>{user[4]:.2f} $</b>\n'
        f'⬇️ Пополнений: <b>{user[5]:.2f} $</b>\n'
        f'⬆️ Выводов: <b>{user[6]:.2f} $</b>\n'
        f'🔄 Кешбэк (5%): <b>{real_cashback:.2f} $</b>\n'
        f'👥 Приведено друзей: <b>{user[7] or 0}</b>\n'
        f'🎮 Сыграно игр: <b>{stats.get("games_played", 0)}</b>\n\n'
        f'🏆 <b>Статус:</b> {get_status(user[3])}'
    )
    await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode='HTML')
    await callback.answer()

def get_status(balance: float):
    if balance >= 1000:
        return '💎 ВИП'
    elif balance >= 500:
        return '🌟 ЗОЛОТОЙ'
    elif balance >= 100:
        return '🥇 СЕРЕБРЯНЫЙ'
    else:
        return '🟢 НОВИЧОК'

@dp.callback_query(F.data == 'wallet')
async def wallet(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    text = (
        f'💰 <b>Кошелёк</b>\n\n'
        f'Баланс: <b>{user[3]:.2f} $</b>\n\n'
        f'📌 Мин. пополнение: {MIN_DEPOSIT} $\n'
        f'📌 Мин. вывод: 2$\n'
        f'📌 Условие вывода: пополнение от 1$\n'
        f'💳 Комиссия: 0%\n'
        f'⏱ Вывод до 24 часов\n\n'
        f'🔒 <b>Все транзакции защищены</b>'
    )
    await callback.message.edit_text(text, reply_markup=wallet_kb(), parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data == 'top')
async def top_players_callback(callback: CallbackQuery):
    await cmd_top(callback.message)

@dp.callback_query(F.data == 'deposit')
async def deposit_menu(callback: CallbackQuery):
    text = (
        '⬇️ <b>Пополнение через криптовалюту</b>\n\n'
        '💰 Поддерживаемые валюты: <b>USDT (TRC-20)</b>\n'
        '📌 Минимальная сумма: <b>1 USDT</b>\n'
        '🎁 Бонус: <b>+10%</b> к сумме\n\n'
        '📝 <b>Инструкция:</b>\n'
        '1. Введи сумму: <code>/deposit 10</code>\n'
        '2. Оплати по ссылке\n'
        '3. Баланс обновится автоматически\n\n'
        '🔒 <b>Безопасно и быстро</b>'
    )
    await callback.message.edit_text(text, reply_markup=back_kb('wallet'), parse_mode='HTML')
    await callback.answer()

@dp.message(Command('deposit'))
async def cmd_deposit(message: Message):
    if not crypto_bot:
        await message.answer('❌ Платежный сервис временно недоступен.')
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            '❌ Укажи сумму:\n<code>/deposit 10</code>\nМинимум — 1 USDT',
            parse_mode='HTML'
        )
        return
    try:
        amount = float(args[1].replace(',', '.'))
        if amount < MIN_DEPOSIT:
            await message.answer(f'❌ Минимальная сумма — {MIN_DEPOSIT} USDT')
            return
        if amount > 10000:
            await message.answer('❌ Максимальная сумма — 10 000 USDT')
            return
    except ValueError:
        await message.answer('❌ Введи число, например: /deposit 10')
        return
    
    if message.from_user.id not in user_stats:
        user_stats[message.from_user.id] = {'total_deposits': 0, 'games_played': 0}
    user_stats[message.from_user.id]['total_deposits'] += amount
    
    invoice = await crypto_bot.create_invoice(
        amount=amount,
        user_id=message.from_user.id,
        currency='USDT',
        description=f'Пополнение для {message.from_user.full_name}'
    )
    if not invoice:
        await message.answer('❌ Ошибка создания счёта. Попробуй позже.')
        return
    order_id = f'user_{message.from_user.id}_{int(time.time())}'
    await save_invoice(
        user_id=message.from_user.id,
        invoice_id=invoice['invoice_id'],
        order_id=order_id,
        amount=amount,
        asset='USDT'
    )
    text = (
        f'💳 <b>Счёт создан!</b>\n\n'
        f'💰 Сумма: <b>{amount:.2f} USDT</b>\n'
        f'🎁 Бонус: +<b>{amount * 0.1:.2f} USDT</b>\n'
        f'🆔 ID: <code>{invoice["invoice_id"]}</code>\n\n'
        f'🔗 <b>Ссылка для оплаты:</b>\n'
        f'{invoice["url"]}\n\n'
        f'⏳ После оплаты баланс обновится автоматически.'
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔗 Оплатить', url=invoice["url"])],
        [InlineKeyboardButton(text='🔄 Проверить оплату', callback_data=f'check_payment_{invoice["invoice_id"]}')],
        [InlineKeyboardButton(text='◀️ Назад', callback_data='wallet')]
    ])
    await message.answer(text, reply_markup=kb, parse_mode='HTML')

@dp.callback_query(F.data.startswith('check_payment_'))
async def check_payment_callback(callback: CallbackQuery):
    if not crypto_bot:
        await callback.answer('❌ Сервис недоступен', show_alert=True)
        return
    invoice_id = int(callback.data.split('_')[2])
    status_data = await crypto_bot.get_invoice_status(invoice_id)
    if not status_data:
        await callback.answer('❌ Ошибка проверки', show_alert=True)
        return
    if status_data['status'] == 'paid':
        paid_amount = status_data['paid_amount']
        bonus = paid_amount * 0.1
        await update_balance(callback.from_user.id, paid_amount + bonus)
        await add_transaction(callback.from_user.id, 'deposit', paid_amount, 'crypto', f'invoice_{invoice_id}')
        await add_transaction(callback.from_user.id, 'bonus', bonus, 'deposit_bonus', '+10% бонус за пополнение')
        await update_invoice_status(invoice_id, 'paid')
        user = await get_user(callback.from_user.id)
        await callback.message.edit_text(
            f'✅ <b>Оплата подтверждена!</b>\n\n'
            f'💰 Зачислено: <b>{paid_amount:.2f} USDT</b>\n'
            f'🎁 Бонус: <b>+{bonus:.2f} USDT</b>\n'
            f'💎 Баланс: <b>{user[3]:.2f} $</b>\n\n'
            f'🎯 Удачной игры!',
            reply_markup=back_kb('wallet'),
            parse_mode='HTML'
        )
        await callback.answer('✅ Оплата подтверждена!')
    elif status_data['status'] == 'pending':
        await callback.answer('⏳ Счёт ещё не оплачен', show_alert=True)
    else:
        await callback.answer('❌ Статус: ' + status_data['status'], show_alert=True)

@dp.callback_query(F.data == 'withdraw')
async def withdraw_start(callback: CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    if user[3] < 2.0:
        await callback.answer('Минимальный вывод 2$', show_alert=True)
        return
    if user[5] < 1.0:
        await callback.answer('Чтобы вывести, нужно пополнить баланс хотя бы на 1$', show_alert=True)
        return
    await state.set_state(BetState.waiting_withdraw)
    await callback.message.edit_text(
        f'⬆️ <b>Вывод средств</b>\n\n'
        f'💰 Баланс: <b>{user[3]:.2f} $</b>\n'
        f'📌 Мин. вывод: <b>2$</b>\n'
        f'📌 Условие: пополнение от 1$\n'
        f'⏱ Время вывода: до 24 часов\n'
        f'💳 Комиссия: 0%\n\n'
        f'Введите сумму для вывода:',
        reply_markup=back_kb('wallet'),
        parse_mode='HTML'
    )
    await callback.answer()

@dp.message(BetState.waiting_withdraw)
async def process_withdraw(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
    except ValueError:
        await message.answer('❌ Введите число, например: 5')
        return
    user = await get_user(message.from_user.id)
    if amount < 2.0:
        await message.answer('❌ Минимальный вывод 2$')
        return
    if amount > user[3]:
        await message.answer('❌ Недостаточно средств')
        return
    if user[5] < 1.0:
        await message.answer('❌ Чтобы вывести, нужно пополнить баланс хотя бы на 1$')
        return
    await update_balance(message.from_user.id, -amount)
    await add_transaction(message.from_user.id, 'withdraw', amount, 'pending')
    await state.clear()
    if ADMINS:
        for admin_id in ADMINS:
            try:
                await bot.send_message(
                    admin_id,
                    f'📢 <b>НОВАЯ ЗАЯВКА НА ВЫВОД!</b>\n\n'
                    f'👤 Пользователь: {message.from_user.full_name}\n'
                    f'🆔 ID: <code>{message.from_user.id}</code>\n'
                    f'💰 Сумма: <b>{amount:.2f} $</b>\n'
                    f'📅 Время: {time.strftime("%Y-%m-%d %H:%M:%S")}\n\n'
                    f'Статус: <b>⏳ Ожидает</b>',
                    parse_mode='HTML'
                )
            except:
                pass
    await message.answer(
        f'✅ <b>Заявка на вывод создана!</b>\n\n'
        f'💰 Сумма: <b>{amount:.2f} $</b>\n'
        f'⏱ Время обработки: до 24 часов\n'
        f'📌 Статус: <b>⏳ Ожидает</b>\n\n'
        f'Вы получите уведомление, когда заявка будет обработана.',
        parse_mode='HTML',
        reply_markup=main_menu_kb()
    )

@dp.message(Command('withdraws'))
async def list_withdraws(message: Message):
    if message.from_user.id not in ADMINS:
        await message.answer('❌ Только для админов!')
        return
    import aiosqlite
    from database import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, user_id, amount, status, created_at FROM transactions WHERE type = 'withdraw' AND status = 'pending' ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await message.answer('📭 Нет активных заявок на вывод.')
        return
    text = '📋 <b>ЗАЯВКИ НА ВЫВОД</b>\n\n'
    for row in rows:
        text += f'🆔 #{row[0]} | Пользователь: <code>{row[1]}</code> | 💰 {row[2]:.2f}$ | {row[3]}\n'
    await message.answer(text, parse_mode='HTML')

@dp.message(Command('confirm_withdraw'))
async def confirm_withdraw(message: Message):
    if message.from_user.id not in ADMINS:
        await message.answer('❌ Только для админов!')
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer('Использование: /confirm_withdraw ID_заявки')
            return
        transaction_id = int(parts[1])
        import aiosqlite
        from database import DB_PATH
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE transactions SET status = 'completed' WHERE id = ? AND type = 'withdraw'",
                (transaction_id,)
            )
            await db.commit()
            async with db.execute(
                "SELECT user_id, amount FROM transactions WHERE id = ?",
                (transaction_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if row:
            user_id, amount = row
            try:
                await bot.send_message(
                    user_id,
                    f'✅ <b>Ваша заявка на вывод подтверждена!</b>\n\n'
                    f'💰 Сумма: <b>{amount:.2f} $</b>\n'
                    f'💳 Средства отправлены на ваш кошелёк.\n\n'
                    f'🎯 Спасибо, что играете с нами!',
                    parse_mode='HTML'
                )
            except:
                pass
        await message.answer(f'✅ Вывод #{transaction_id} подтверждён! Пользователь уведомлён.')
    except ValueError:
        await message.answer('❌ ID должен быть числом!')
    except Exception as e:
        await message.answer(f'❌ Ошибка: {e}')

async def check_pending_payments():
    while True:
        try:
            if not crypto_bot:
                await asyncio.sleep(30)
                continue
            pending = await get_pending_invoices()
            for invoice_record in pending:
                record_id, user_id, invoice_id, amount, asset, order_id = invoice_record
                status_data = await crypto_bot.get_invoice_status(invoice_id)
                if not status_data:
                    continue
                if status_data['status'] == 'paid':
                    paid_amount = status_data['paid_amount']
                    bonus = paid_amount * 0.1
                    await update_balance(user_id, paid_amount + bonus)
                    await add_transaction(user_id, 'deposit', paid_amount, 'crypto', order_id)
                    await add_transaction(user_id, 'bonus', bonus, 'deposit_bonus', '+10% бонус за пополнение')
                    await update_invoice_status(invoice_id, 'paid')
                    try:
                        await bot.send_message(
                            user_id,
                            f'✅ <b>Пополнение успешно!</b>\n\n'
                            f'💰 Зачислено: <b>{paid_amount:.2f} USDT</b>\n'
                            f'🎁 Бонус: +<b>{bonus:.2f} USDT</b>\n\n'
                            f'🎯 Удачной игры!',
                            parse_mode='HTML'
                        )
                    except:
                        pass
                    if ADMINS:
                        for admin_id in ADMINS:
                            try:
                                await bot.send_message(
                                    admin_id,
                                    f'💳 <b>ПОПОЛНЕНИЕ</b>\n\n'
                                    f'👤 ID: <code>{user_id}</code>\n'
                                    f'💰 Сумма: <b>{paid_amount:.2f} USDT</b>\n'
                                    f'🎁 Бонус: +<b>{bonus:.2f} USDT</b>',
                                    parse_mode='HTML'
                                )
                            except:
                                pass
                    logger.info(f'Payment confirmed: user {user_id}, {paid_amount} USDT')
                elif status_data['status'] in ['expired', 'failed', 'cancelled']:
                    await update_invoice_status(invoice_id, status_data['status'])
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f'Payment check error: {e}')
            await asyncio.sleep(60)

@dp.callback_query(F.data.startswith('game_'))
async def select_game(callback: CallbackQuery):
    game = callback.data.replace('game_', '')
    names = {
        'dice': '🎲 Куб (чёт/нечет)',
        'roulette': '🎡 Рулетка',
        'coinflip': '🪙 Орёл/Решка',
        'mines': '💣 Мины',
        'tower': '🗼 Башня'
    }
    user = await get_user(callback.from_user.id)
    text = f'{names.get(game, game)}\n\n💰 Баланс: <b>{user[3]:.2f} $</b>\nВыберите ставку:'
    await callback.message.edit_text(text, reply_markup=bet_kb(game), parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data.startswith('bet_'))
async def process_bet(callback: CallbackQuery, state: FSMContext):
    data = callback.data
    if data.startswith('bet_custom_'):
        game = data.replace('bet_custom_', '')
        await state.set_state(BetState.waiting_custom_bet)
        await state.update_data(game=game)
        await callback.message.edit_text(f'✏️ Введите свою сумму (мин. {MIN_BET} $):', reply_markup=back_kb('play'))
        await callback.answer()
        return
    parts = data.split('_')
    game = parts[1]
    amount = float(parts[2])
    
    if game == 'dice':
        await callback.message.edit_text(
            f'🎲 <b>Куб</b>\n\nСтавка: <b>{amount:.2f} $</b>\nВыберите:',
            reply_markup=dice_choice_kb(game, amount),
            parse_mode='HTML'
        )
        await callback.answer()
        return
    
    if game == 'roulette':
        await callback.message.edit_text(
            f'🎡 <b>Рулетка</b>\n\nСтавка: <b>{amount:.2f} $</b>\nВыберите тип ставки:',
            reply_markup=roulette_bet_kb(game, amount),
            parse_mode='HTML'
        )
        await callback.answer()
        return
    
    if game == 'coinflip':
        await callback.message.edit_text(
            f'🪙 <b>Орёл/Решка</b>\n\nСтавка: <b>{amount:.2f} $</b>\nВыберите:',
            reply_markup=coinflip_kb(game, amount),
            parse_mode='HTML'
        )
        await callback.answer()
        return
    
    await start_game(callback, game, amount)

@dp.message(BetState.waiting_custom_bet)
async def custom_bet(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
    except ValueError:
        await message.answer('❌ Введите число (например: 5)')
        return
    if amount < MIN_BET:
        await message.answer(f'❌ Минимальная ставка {MIN_BET} $')
        return
    data = await state.get_data()
    game = data.get('game')
    await state.clear()
    
    user = await get_user(message.from_user.id)
    if user[3] < amount:
        await message.answer('❌ Недостаточно средств')
        return
    
    await update_balance(message.from_user.id, -amount, is_turnover=True)
    
    if message.from_user.id not in user_stats:
        user_stats[message.from_user.id] = {'total_deposits': 0, 'games_played': 0}
    user_stats[message.from_user.id]['games_played'] += 1
    
    if game == 'mines':
        await start_mines_from_message(message, amount)
    elif game == 'tower':
        await start_tower_from_message(message, amount)
    else:
        await message.answer('❌ Игра в разработке')

async def start_game(callback, game: str, amount: float):
    user = await get_user(callback.from_user.id)
    if user[3] < amount:
        await callback.answer('Недостаточно средств', show_alert=True)
        return
    await update_balance(callback.from_user.id, -amount, is_turnover=True)
    
    if callback.from_user.id not in user_stats:
        user_stats[callback.from_user.id] = {'total_deposits': 0, 'games_played': 0}
    user_stats[callback.from_user.id]['games_played'] += 1
    
    if game == 'mines':
        await start_mines(callback, amount)
    elif game == 'tower':
        await start_tower(callback, amount)
    else:
        await callback.message.answer('❌ Игра в разработке')

# ==================== КУБ ====================

@dp.callback_query(F.data.startswith('dice_'))
async def dice_choice(callback: CallbackQuery):
    parts = callback.data.split('_')
    choice = parts[1]  # even или odd
    game = parts[2]
    amount = float(parts[3])
    
    user = await get_user(callback.from_user.id)
    if user[3] < amount:
        await callback.answer('Недостаточно средств', show_alert=True)
        return
    
    await update_balance(callback.from_user.id, -amount, is_turnover=True)
    
    # 35% шанс на выигрыш
    roll = random.random()
    win = 0.0
    is_win = roll < 0.35
    
    if is_win:
        win = amount * 2
        result_text = f'✅ Выигрыш: <b>{win:.2f} $</b>'
        await update_balance(callback.from_user.id, win)
    else:
        result_text = '❌ Проигрыш'
        cashback = amount * 0.05
        await update_balance(callback.from_user.id, cashback)
        await add_transaction(callback.from_user.id, 'cashback', cashback, 'cashback', f'Кешбэк 5% от {amount:.2f}$')
    
    value = random.randint(1, 6)
    is_even = value % 2 == 0
    selected = 'ЧЁТ' if choice == 'even' else 'НЕЧЕТ'
    
    user = await get_user(callback.from_user.id)
    text = (
        f'🎲 <b>Куб</b>\n\n'
        f'Выпало: <b>{value}</b> ({"ЧЁТ" if is_even else "НЕЧЕТ"})\n'
        f'Ваша ставка: {selected}\n'
        f'{result_text}\n\n'
        f'💰 Баланс: <b>{user[3]:.2f} $</b>'
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔄 Ещё раз', callback_data='game_dice')],
        [InlineKeyboardButton(text='🎮 К играм', callback_data='play'),
         InlineKeyboardButton(text='🏠 Меню', callback_data='back_main')]
    ])
    await callback.message.answer(text, reply_markup=kb, parse_mode='HTML')
    await callback.answer()

# ==================== РУЛЕТКА ====================

async def roulette_animation(callback: CallbackQuery, result_num: int):
    emojis = ['🎡', '🌀', '🎰', '🎡', '🌀', '🎰']
    spin_numbers = []
    for _ in range(6):
        spin_numbers.append(random.randint(0, 36))
    spin_numbers.append(result_num)
    msg = await callback.message.answer("🎡 Рулетка крутится...")
    for i, num in enumerate(spin_numbers):
        if num == 0:
            color = '🟢'
        elif num in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]:
            color = '🔴'
        else:
            color = '⚫'
        await msg.edit_text(
            f"{emojis[i % len(emojis)]} <b>Вращение...</b>\n\n"
            f"Выпало: <b>{num}</b> {color}\n"
            f"{'━' * (i + 1)}{'━' * (6 - i - 1)}",
            parse_mode='HTML'
        )
        await asyncio.sleep(0.5)
    return msg

@dp.callback_query(F.data.startswith('roulette_type_'))
async def roulette_type_choice(callback: CallbackQuery):
    parts = callback.data.split('_')
    bet_type = parts[2]
    game = parts[3]
    amount = float(parts[4])
    if bet_type == 'number':
        await callback.message.edit_text(
            f'🎡 <b>Рулетка</b>\n\nСтавка: <b>{amount:.2f} $</b>\nВыберите число:',
            reply_markup=roulette_number_kb(game, amount),
            parse_mode='HTML'
        )
    else:
        await callback.message.edit_text(
            f'🎡 <b>Рулетка</b>\n\nСтавка: <b>{amount:.2f} $</b>\nВыберите цвет:',
            reply_markup=roulette_color_kb(game, amount),
            parse_mode='HTML'
        )
    await callback.answer()

@dp.callback_query(F.data.startswith('roulette_num_'))
async def roulette_number_choice(callback: CallbackQuery):
    parts = callback.data.split('_')
    number = int(parts[2])
    game = parts[3]
    amount = float(parts[4])
    
    user = await get_user(callback.from_user.id)
    if user[3] < amount:
        await callback.answer('Недостаточно средств', show_alert=True)
        return
    
    await update_balance(callback.from_user.id, -amount, is_turnover=True)
    
    roll = random.random()
    win = 0.0
    is_win = roll < 0.015
    
    if is_win:
        win = amount * 35
        result_text = f'🔥 ДЖЕКПОТ! x35!\n✅ Выигрыш: <b>{win:.2f} $</b>'
        await update_balance(callback.from_user.id, win)
    else:
        result_text = '❌ Проигрыш'
        cashback = amount * 0.05
        await update_balance(callback.from_user.id, cashback)
        await add_transaction(callback.from_user.id, 'cashback', cashback, 'cashback', f'Кешбэк 5% от {amount:.2f}$')
    
    result_num = random.randint(0, 36)
    await roulette_animation(callback, result_num)
    
    if result_num == 0:
        result_color = '🟢'
    elif result_num in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]:
        result_color = '🔴'
    else:
        result_color = '⚫'
    
    user = await get_user(callback.from_user.id)
    text = (
        f'🎡 <b>Рулетка</b>\n\n'
        f'Выпало: <b>{result_num}</b> {result_color}\n'
        f'{result_text}\n\n'
        f'💰 Баланс: <b>{user[3]:.2f} $</b>'
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔄 Ещё раз', callback_data='game_roulette')],
        [InlineKeyboardButton(text='🎮 К играм', callback_data='play'),
         InlineKeyboardButton(text='🏠 Меню', callback_data='back_main')]
    ])
    await callback.message.answer(text, reply_markup=kb, parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data.startswith('roulette_color_'))
async def roulette_color_choice(callback: CallbackQuery):
    parts = callback.data.split('_')
    bet_color = parts[2]
    game = parts[3]
    amount = float(parts[4])
    
    user = await get_user(callback.from_user.id)
    if user[3] < amount:
        await callback.answer('Недостаточно средств', show_alert=True)
        return
    
    await update_balance(callback.from_user.id, -amount, is_turnover=True)
    
    roll = random.random()
    win = 0.0
    is_win = roll < 0.35
    
    if is_win:
        win = amount * 2
        result_text = f'✅ Выигрыш: <b>{win:.2f} $</b>'
        await update_balance(callback.from_user.id, win)
    else:
        result_text = '❌ Проигрыш'
        cashback = amount * 0.05
        await update_balance(callback.from_user.id, cashback)
        await add_transaction(callback.from_user.id, 'cashback', cashback, 'cashback', f'Кешбэк 5% от {amount:.2f}$')
    
    result_num = random.randint(0, 36)
    await roulette_animation(callback, result_num)
    
    if result_num == 0:
        result_color = '🟢'
    elif result_num in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]:
        result_color = '🔴'
    else:
        result_color = '⚫'
    
    user = await get_user(callback.from_user.id)
    text = (
        f'🎡 <b>Рулетка</b>\n\n'
        f'Выпало: <b>{result_num}</b> {result_color}\n'
        f'{result_text}\n\n'
        f'💰 Баланс: <b>{user[3]:.2f} $</b>'
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔄 Ещё раз', callback_data='game_roulette')],
        [InlineKeyboardButton(text='🎮 К играм', callback_data='play'),
         InlineKeyboardButton(text='🏠 Меню', callback_data='back_main')]
    ])
    await callback.message.answer(text, reply_markup=kb, parse_mode='HTML')
    await callback.answer()

# ==================== ОРЁЛ/РЕШКА ====================

@dp.callback_query(F.data.startswith('coinflip_'))
async def coinflip_choice(callback: CallbackQuery):
    parts = callback.data.split('_')
    choice = parts[1]  # eagle или tails
    game = parts[2]
    amount = float(parts[3])
    
    user = await get_user(callback.from_user.id)
    if user[3] < amount:
        await callback.answer('Недостаточно средств', show_alert=True)
        return
    
    await update_balance(callback.from_user.id, -amount, is_turnover=True)
    
    roll = random.random()
    win = 0.0
    is_win = roll < 0.35
    
    if is_win:
        win = amount * 2
        result_text = f'✅ Выигрыш: <b>{win:.2f} $</b>'
        await update_balance(callback.from_user.id, win)
    else:
        result_text = '❌ Проигрыш'
        cashback = amount * 0.05
        await update_balance(callback.from_user.id, cashback)
        await add_transaction(callback.from_user.id, 'cashback', cashback, 'cashback', f'Кешбэк 5% от {amount:.2f}$')
    
    result = random.choice(['eagle', 'tails'])
    emoji = '🦅' if result == 'eagle' else '🪙'
    name = 'ОРЁЛ' if result == 'eagle' else 'РЕШКА'
    
    user = await get_user(callback.from_user.id)
    text = (
        f'🪙 <b>Орёл/Решка</b>\n\n'
        f'Выпало: {emoji} <b>{name}</b>\n'
        f'{result_text}\n\n'
        f'💰 Баланс: <b>{user[3]:.2f} $</b>'
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔄 Ещё раз', callback_data='game_coinflip')],
        [InlineKeyboardButton(text='🎮 К играм', callback_data='play'),
         InlineKeyboardButton(text='🏠 Меню', callback_data='back_main')]
    ])
    await callback.message.answer(text, reply_markup=kb, parse_mode='HTML')
    await callback.answer()

# ==================== МИНЫ ====================

async def start_mines(callback, amount: float):
    user_id = callback.from_user.id
    size = 5
    bombs_count = 8
    total = size * size
    bomb_positions = list(random.sample(range(total), bombs_count))
    set_game(user_id, {
        'type': 'mines',
        'bet': amount,
        'bombs': bomb_positions,
        'opened': [],
        'multiplier': 1.0,
        'size': size,
        'active': True
    })
    text = (
        f'💣 <b>Мины</b>\n\n'
        f'💰 Ставка: <b>{amount:.2f} $</b>\n'
        f'💎 Множитель: <b>x1.00</b>\n\n'
        f'Открывай клетки и избегай мин!'
    )
    kb = build_mines_keyboard(user_id)
    await callback.message.answer(text, reply_markup=kb, parse_mode='HTML')
    await callback.answer()

async def start_mines_from_message(message: Message, amount: float):
    user_id = message.from_user.id
    size = 5
    bombs_count = 8
    total = size * size
    bomb_positions = list(random.sample(range(total), bombs_count))
    set_game(user_id, {
        'type': 'mines',
        'bet': amount,
        'bombs': bomb_positions,
        'opened': [],
        'multiplier': 1.0,
        'size': size,
        'active': True
    })
    text = (
        f'💣 <b>Мины</b>\n\n'
        f'💰 Ставка: <b>{amount:.2f} $</b>\n'
        f'💎 Множитель: <b>x1.00</b>\n\n'
        f'Открывай клетки и избегай мин!'
    )
    kb = build_mines_keyboard(user_id)
    await message.answer(text, reply_markup=kb, parse_mode='HTML')

def build_mines_keyboard(user_id: int, revealed: bool = False):
    game = get_game(user_id)
    if not game or not game.get('active'):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🔄 Играть снова', callback_data='game_mines')],
            [InlineKeyboardButton(text='🎮 К играм', callback_data='play')]
        ])
    size = game['size']
    bombs = set(game['bombs'])
    opened = set(game['opened'])
    kb = []
    for r in range(size):
        row = []
        for c in range(size):
            pos = r * size + c
            if revealed or pos in opened:
                if pos in bombs:
                    row.append(InlineKeyboardButton(text='💣', callback_data='ignore_mines'))
                else:
                    row.append(InlineKeyboardButton(text='💎', callback_data='ignore_mines'))
            else:
                row.append(InlineKeyboardButton(text='⬜', callback_data=f'mines_{pos}'))
        kb.append(row)
    if not revealed and opened:
        cashout = game['bet'] * game['multiplier']
        kb.append([InlineKeyboardButton(text=f'💰 Забрать {cashout:.2f}$', callback_data='mines_cashout')])
    kb.append([InlineKeyboardButton(text='◀️ Выход', callback_data='play')])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data.startswith('mines_'))
async def mines_click(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = get_game(user_id)
    if not game or game.get('type') != 'mines' or not game.get('active'):
        await callback.answer('♻️ Игра завершена. Начни новую!', show_alert=True)
        return
    data = callback.data
    if data == 'mines_cashout':
        win = game['bet'] * game['multiplier']
        await update_balance(user_id, win)
        game['active'] = False
        delete_game(user_id)
        user = await get_user(user_id)
        text = f'💣 <b>Мины</b>\n\n✅ Забрал: <b>{win:.2f} $</b>\n\n💰 Баланс: <b>{user[3]:.2f} $</b>'
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🔄 Ещё раз', callback_data='game_mines')],
            [InlineKeyboardButton(text='🎮 К играм', callback_data='play')]
        ])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode='HTML')
        await callback.answer()
        return
    if data == 'ignore_mines':
        await callback.answer()
        return
    pos = int(data.split('_')[1])
    bombs = set(game['bombs'])
    opened = set(game['opened'])
    if pos in opened:
        await callback.answer()
        return
    if pos in bombs:
        game['active'] = False
        delete_game(user_id)
        text = f'💣 <b>Мины</b>\n\n💥 Ты попал на мину!\n❌ Ставка {game["bet"]:.2f}$ сгорела.'
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🔄 Играть снова', callback_data='game_mines')],
            [InlineKeyboardButton(text='🎮 К играм', callback_data='play')]
        ])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode='HTML')
        await callback.answer('💥 Мина!')
        return
    opened.add(pos)
    game['opened'] = list(opened)
    game['multiplier'] = round(1.0 + len(opened) * 0.15, 2)
    text = (
        f'💣 <b>Мины</b>\n\n'
        f'💰 Ставка: <b>{game["bet"]:.2f} $</b>\n'
        f'💎 Множитель: <b>x{game["multiplier"]}</b>\n'
        f'Открыто: {len(opened)}\n\n'
        f'Продолжай или забери выигрыш!'
    )
    kb = build_mines_keyboard(user_id)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode='HTML')
    await callback.answer('💎 Есть!')

# ==================== БАШНЯ ====================

async def start_tower(callback, amount: float):
    user_id = callback.from_user.id
    rows, cols = 7, 5
    bombs_count = 12
    total = rows * cols
    bomb_positions = list(random.sample(range(total), bombs_count))
    set_game(user_id, {
        'type': 'tower',
        'bet': amount,
        'bombs': bomb_positions,
        'opened': [],
        'current_row': 0,
        'multiplier': 1.0,
        'rows': rows,
        'cols': cols,
        'active': True
    })
    text = (
        f'🗼 <b>Игра «Башня»</b>\n\n'
        f'💰 Ставка: <b>{amount:.2f} $</b>\n'
        f'💎 Множитель: <b>x1.00</b>\n\n'
        f'Выбирай клетку в нижнем ряду!\n'
        f'Избегай динамита 💥'
    )
    kb = build_tower_keyboard(user_id)
    await callback.message.answer(text, reply_markup=kb, parse_mode='HTML')
    await callback.answer()

async def start_tower_from_message(message: Message, amount: float):
    user_id = message.from_user.id
    rows, cols = 7, 5
    bombs_count = 12
    total = rows * cols
    bomb_positions = list(random.sample(range(total), bombs_count))
    set_game(user_id, {
        'type': 'tower',
        'bet': amount,
        'bombs': bomb_positions,
        'opened': [],
        'current_row': 0,
        'multiplier': 1.0,
        'rows': rows,
        'cols': cols,
        'active': True
    })
    text = (
        f'🗼 <b>Игра «Башня»</b>\n\n'
        f'💰 Ставка: <b>{amount:.2f} $</b>\n'
        f'💎 Множитель: <b>x1.00</b>\n\n'
        f'Выбирай клетку в нижнем ряду!\n'
        f'Избегай динамита 💥'
    )
    kb = build_tower_keyboard(user_id)
    await message.answer(text, reply_markup=kb, parse_mode='HTML')

def build_tower_keyboard(user_id: int, revealed: bool = False):
    game = get_game(user_id)
    if not game or not game.get('active'):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🔄 Играть снова', callback_data='game_tower')],
            [InlineKeyboardButton(text='🎮 К играм', callback_data='play')]
        ])
    rows, cols = game['rows'], game['cols']
    bombs = set(game['bombs'])
    opened = set(game['opened'])
    current_row = game['current_row']
    kb = []
    for r in range(rows - 1, -1, -1):
        row_btns = []
        for c in range(cols):
            pos = r * cols + c
            if revealed or pos in opened:
                if pos in bombs:
                    row_btns.append(InlineKeyboardButton(text='💥', callback_data='ignore_tower'))
                else:
                    row_btns.append(InlineKeyboardButton(text='💎', callback_data='ignore_tower'))
            else:
                if r == current_row:
                    row_btns.append(InlineKeyboardButton(text='⬜', callback_data=f'tower_{pos}'))
                else:
                    row_btns.append(InlineKeyboardButton(text='⬛', callback_data='ignore_tower'))
        kb.append(row_btns)
    if not revealed and opened:
        cashout = game['bet'] * game['multiplier']
        kb.append([InlineKeyboardButton(text=f'💰 Забрать {cashout:.2f}$', callback_data='tower_cashout')])
    kb.append([InlineKeyboardButton(text='◀️ Выход', callback_data='play')])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data.startswith('tower_'))
async def tower_click(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = get_game(user_id)
    if not game or game.get('type') != 'tower' or not game.get('active'):
        await callback.answer('♻️ Игра завершена. Начни новую!', show_alert=True)
        return
    data = callback.data
    if data == 'tower_cashout':
        win = game['bet'] * game['multiplier']
        await update_balance(user_id, win)
        game['active'] = False
        delete_game(user_id)
        user = await get_user(user_id)
        text = (
            f'🗼 <b>Башня</b>\n\n'
            f'✅ Ты забрал выигрыш!\n'
            f'💰 Получено: <b>{win:.2f} $</b>\n\n'
            f'💰 Баланс: <b>{user[3]:.2f} $</b>'
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🔄 Ещё раз', callback_data='game_tower')],
            [InlineKeyboardButton(text='🎮 К играм', callback_data='play')]
        ])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode='HTML')
        await callback.answer()
        return
    if data == 'ignore_tower':
        await callback.answer()
        return
    pos = int(data.split('_')[1])
    row = pos // game['cols']
    bombs = set(game['bombs'])
    opened = set(game['opened'])
    current_row = game['current_row']
    if row != current_row:
        await callback.answer('Выбирай только текущий ряд!', show_alert=True)
        return
    if pos in bombs:
        game['active'] = False
        delete_game(user_id)
        text = (
            f'🗼 <b>Башня</b>\n\n'
            f'💥 Ты наткнулся на динамит!\n'
            f'❌ Ставка {game["bet"]:.2f}$ сгорела.'
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🔄 Играть снова', callback_data='game_tower')],
            [InlineKeyboardButton(text='🎮 К играм', callback_data='play')]
        ])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode='HTML')
        await callback.answer('💥 Динамит!')
        return
    opened.add(pos)
    game['opened'] = list(opened)
    game['current_row'] += 1
    game['multiplier'] = round(1.0 + game['current_row'] * 0.25, 2)
    if game['current_row'] >= game['rows']:
        win = game['bet'] * game['multiplier']
        await update_balance(user_id, win)
        game['active'] = False
        delete_game(user_id)
        user = await get_user(user_id)
        text = (
            f'🗼 <b>Башня пройдена!</b>\n\n'
            f'🔥 Множитель x{game["multiplier"]}\n'
            f'✅ Выигрыш: <b>{win:.2f} $</b>\n\n'
            f'💰 Баланс: <b>{user[3]:.2f} $</b>'
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='🔄 Ещё раз', callback_data='game_tower')],
            [InlineKeyboardButton(text='🎮 К играм', callback_data='play')]
        ])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode='HTML')
        await callback.answer('🔥 Победа!')
        return
    text = (
        f'🗼 <b>Игра «Башня»</b>\n\n'
        f'💰 Ставка: <b>{game["bet"]:.2f} $</b>\n'
        f'💎 Множитель: <b>x{game["multiplier"]}</b>\n'
        f'Ряд: {game["current_row"] + 1}/{game["rows"]}\n\n'
        f'Выбирай клетку дальше или забери выигрыш!'
    )
    kb = build_tower_keyboard(user_id)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode='HTML')
    await callback.answer('💎 Есть!')

@dp.message(Command('addbalance'))
async def add_balance_cmd(message: Message):
    if message.from_user.id not in ADMINS:
        await message.answer('❌ Только для админов!')
        return
    try:
        parts = message.text.split()
        user_id = int(parts[1])
        amount = float(parts[2])
        await update_balance(user_id, amount)
        await add_transaction(user_id, 'deposit', amount, 'admin')
        await message.answer(f'✅ Начислено {amount}$ пользователю {user_id}')
    except:
        await message.answer('Использование: /addbalance ID сумма\nПример: /addbalance 123456 10')

async def set_commands():
    commands = [
        BotCommand(command='start', description='🏠 Главное меню'),
        BotCommand(command='menu', description='🏠 Главное меню'),
        BotCommand(command='games', description='🎮 Список игр'),
        BotCommand(command='top', description='🏆 Топ игроков'),
        BotCommand(command='deposit', description='💰 Пополнить баланс'),
        BotCommand(command='withdraw', description='💸 Вывод средств (мин. 2$, пополни 1$)'),
        BotCommand(command='help', description='❓ Помощь'),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())

async def main():
    await init_db()
    await set_commands()
    asyncio.create_task(check_pending_payments())
    logger.info('✅ Бот запущен!')
    await dp.start_polling(bot)
