import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from fastapi import FastAPI
import uvicorn

# === Настройки ===
API_TOKEN = "7742988xxx42:AAFwEqJR-agWmMbfPlBRBdgxDSNP3Kxf-0o"  # <-- вставь свой токен

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)

# === Константы ===
MAX_AMMO = 3
RELOAD_SECONDS = 7
ROUND_DURATION = 15 * 60  # 15 минут

# === Стикеры ===
STICKER_SPLASH = "CAACAgUAAxkBAAEGdKhlp3TCMY_EqA1z9zr0CBTKJY93aAACxQIAAladvQpJVm9rckWYbC8E"
STICKER_WIN = "CAACAgUAAxkBAAEGdKtlp3TjUjeTAAGGFcPU7gVKL3aVpQACegIAAladvQpxuylfO8jzIS8E"
STICKER_LOSE = "CAACAgUAAxkBAAEGdKxlp3T4AAGINL_3j5h0T7gxfrc7QbwAAowCAAJWrb0KYrdtT2LOHkUvBA"

# === Игровые данные ===
teams = {"первые": set(), "мироходцы": set()}
hp = {}
ammo = {}
cooldowns = {}
kills = {}
round_end_time = None

# === Интерфейс ===
def game_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🌊 За Первых", callback_data="team_первые"),
         InlineKeyboardButton("🌴 За Мироходцев", callback_data="team_мироходцы")],
        [InlineKeyboardButton("💧 Облить соперника", callback_data="attack")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")]
    ])

# === Обработчики ===
@dp.message_handler(commands=["start"])
async def start_game(message: types.Message):
    global round_end_time
    user = message.from_user
    hp[user.id] = 3
    ammo[user.id] = MAX_AMMO

    if round_end_time is None:
        round_end_time = datetime.now() + timedelta(seconds=ROUND_DURATION)
        asyncio.create_task(round_timer(message.chat.id))

    await message.answer(
        f"🏖 Привет, {user.first_name}! Добро пожаловать в «Водяную битву с флудом!»\n"
        f"Выбери команду и вступай в летний бой!",
        reply_markup=game_keyboard()
    )

@dp.callback_query_handler(lambda c: c.data.startswith("team_"))
async def join_team(callback: types.CallbackQuery):
    team = callback.data.split("_")[1]
    user = callback.from_user

    for t in teams:
        teams[t].discard(user.id)
    teams[team].add(user.id)

    hp[user.id] = 3
    ammo[user.id] = MAX_AMMO

    await callback.answer(f"Ты теперь за команду «{team.title()}»!")

@dp.callback_query_handler(lambda c: c.data == "attack")
async def attack(callback: types.CallbackQuery):
    user = callback.from_user
    user_id = user.id

    # Проверка команды
    team = next((t for t, members in teams.items() if user_id in members), None)
    if not team:
        await callback.answer("Сначала выбери команду!", show_alert=True)
        return

    # Перезарядка
    now = datetime.now()
    if user_id in cooldowns and cooldowns[user_id] > now:
        seconds = (cooldowns[user_id] - now).seconds
        await callback.answer(f"Перезарядка: {seconds} сек.", show_alert=True)
        return

    if ammo.get(user_id, 0) <= 0:
        await callback.answer("💤 У тебя закончились снаряды. Ждём перезарядки.", show_alert=True)
        return

    ammo[user_id] -= 1
    cooldowns[user_id] = now + timedelta(seconds=RELOAD_SECONDS)

    # Найти противника
    enemy_team = "мироходцы" if team == "первые" else "первые"
    if not teams[enemy_team]:
        await callback.answer("☀️ Врагов нет!", show_alert=True)
        return

    target_id = next(iter(teams[enemy_team]))
    hp[target_id] = hp.get(target_id, 3) - 1

    try:
        target_info = await bot.get_chat_member(callback.message.chat.id, target_id)
        await callback.message.answer_sticker(STICKER_SPLASH)
        await callback.message.answer(
            f"💦 {user.first_name} обливает {target_info.user.first_name}!\n"
            f"У него осталось {hp[target_id]} жизней."
        )

        if hp[target_id] <= 0:
            teams[enemy_team].discard(target_id)
            await callback.message.answer(f"💀 {target_info.user.first_name} выбыл!")
            kills[user_id] = kills.get(user_id, 0) + 1

        if not teams[enemy_team]:
            await declare_winner(team, callback.message.chat.id)

    except Exception as e:
        print(f"Ошибка при получении информации о цели: {e}")

@dp.callback_query_handler(lambda c: c.data == "stats")
async def show_stats(callback: types.CallbackQuery):
    if not kills:
        await callback.message.answer("⛱ Пока никто никого не облил.")
        return

    sorted_stats = sorted(kills.items(), key=lambda x: x[1], reverse=True)
    text = "📊 Топ по обливанию:\n"
    for i, (uid, score) in enumerate(sorted_stats[:10], 1):
        try:
            member = await bot.get_chat_member(callback.message.chat.id, uid)
            text += f"{i}. {member.user.first_name} — {score} 💦\n"
        except:
            text += f"{i}. Игрок {uid} — {score} 💦\n"

    await callback.message.answer(text)

# === Таймер раунда ===
async def round_timer(chat_id):
    global round_end_time
    await asyncio.sleep(ROUND_DURATION)

    red = len(teams["первые"])
    blue = len(teams["мироходцы"])

    if red > blue:
        winner = "первые"
    elif blue > red:
        winner = "мироходцы"
    else:
        winner = "draw"

    if winner == "draw":
        await bot.send_message(chat_id, "🤝 Раунд завершён! Ничья.")
    else:
        await declare_winner(winner, chat_id)

    # Сброс
    teams["первые"].clear()
    teams["мироходцы"].clear()
    ammo.clear()
    hp.clear()
    cooldowns.clear()
    kills.clear()
    round_end_time = None

# === Победа ===
async def declare_winner(team, chat_id):
    losers = "мироходцы" if team == "первые" else "первые"

    for uid in teams[team]:
        try:
            await bot.send_sticker(uid, STICKER_WIN)
            await bot.send_message(uid, f"🎉 Победа команды «{team.title()}»!")
        except:
            pass

    for uid in teams[losers]:
        try:
            await bot.send_sticker(uid, STICKER_LOSE)
            await bot.send_message(uid, f"💦 Команда «{team.title()}» вас победила.")
        except:
            pass

# === FastAPI + aiogram запуск ===
app = FastAPI()

@app.get("/")
def root():
    return {"status": "Water battle bot is running!"}

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(dp.start_polling(bot, skip_updates=True))

if name == "main":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
