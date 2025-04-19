import sqlite3
import os
import logging
import asyncio
import threading
import uuid
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from flask import Flask, render_template_string
import pandas as pd
from asciichartpy import plot
import aiohttp

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Конфигурационные переменные
BOT_TOKEN = "7935425343:AAECbjFJvLHkeTvwHAKDG8uvmy-KiWcPtns"
ADMIN_TELEGRAM_ID = 650154766
PORT = os.getenv("PORT", "5000")
RENDER_EXTERNAL_HOSTNAME = "warpxc.onrender.com"

logger.info(f"Загруженные переменные: BOT_TOKEN={'***' if BOT_TOKEN else 'не задан'}, "
            f"ADMIN_TELEGRAM_ID={ADMIN_TELEGRAM_ID}, "
            f"PORT={PORT}, RENDER_EXTERNAL_HOSTNAME={RENDER_EXTERNAL_HOSTNAME}")

# Проверка переменных
if not BOT_TOKEN:
    logger.error("BOT_TOKEN не задан")
    raise ValueError("BOT_TOKEN не задан")

# Инициализация Flask
app = Flask(__name__)
application = None  # Глобальная переменная для Telegram Application

# База данных в памяти
DB_PATH = ":memory:"

# Проверка связи с Telegram API
async def check_telegram_api():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe") as response:
                data = await response.json()
                if data.get("ok"):
                    logger.info("Связь с Telegram API активна")
                    return True, "🟢 Активна"
                else:
                    logger.warning(f"Ошибка Telegram API: {data}")
                    return False, f"🔴 Отсутствует ({data.get('description', 'Неизвестная ошибка')})"
    except Exception as e:
        logger.error(f"Ошибка проверки Telegram API: {e}")
        return False, f"🔴 Отсутствует ({str(e)})"

# Инициализация базы данных и добавление тестовых данных
def init_db():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            first_seen DATETIME,
            last_config_time TEXT,
            is_banned INTEGER DEFAULT 0
        )''')
        c.execute('''CREATE TABLE configs (
            config_id TEXT PRIMARY KEY,
            telegram_id INTEGER,
            created_at DATETIME,
            is_active INTEGER DEFAULT 1,
            FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
        )''')
        conn.commit()
        logger.info("База данных инициализирована в памяти")

        # Добавление тестовых данных
        for i in range(10):
            telegram_id = 12345 + i
            c.execute(
                "INSERT OR IGNORE INTO users (telegram_id, username, first_name, first_seen, is_banned) "
                "VALUES (?, ?, ?, ?, ?)",
                (telegram_id, f"test_user_{i}", f"User{i}", datetime.now() - timedelta(hours=i), 0)
            )
            c.execute(
                "INSERT INTO configs (config_id, telegram_id, created_at, is_active) "
                "VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), telegram_id, datetime.now() - timedelta(hours=i), 1)
            )
        conn.commit()
        logger.info("Тестовые данные добавлены")
    except sqlite3.Error as e:
        logger.error(f"Ошибка инициализации базы данных или добавления тестовых данных: {e}")
        raise
    finally:
        if conn:
            conn.close()
            logger.info("Соединение с базой данных закрыто")

# Генерация WARP конфигурации
def generate_warp_config():
    private_key = f"CS/UQwV5cCjhGdH/1FQbSkRLvYU8Ha1xeTkHVg5rizI={uuid.uuid4().hex[:8]}"
    public_key = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="
    config = f"""[Interface]
PrivateKey = {private_key}
S1 = 0
S2 = 0
Jc = 120
Jmin = 23
Jmax = 911
H1 = 1
H2 = 2
H Nau3 = 3
H4 = 4
MTU = 1280
Address = 172.16.0.2, 2606:4700:110:8a82:ae4c:ce7e:e5a6:a7fd
DNS = 1.1.1.1, 2606:4700:4700::1111, 1.0.0.1, 2606:4700:4700::1001

[Peer]
PublicKey = {public_key}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = 162.159.192.227:894
"""
    return config

# Проверка админ-прав
def is_admin(telegram_id):
    return telegram_id == ADMIN_TELEGRAM_ID

# Получение статистики
def get_stats():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0")
        active_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
        banned_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM configs WHERE is_active = 1")
        active_configs = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM configs")
        total_configs = c.fetchone()[0]
        return active_users, banned_users, active_configs, total_configs
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения статистики: {e}")
        return 0, 0, 0, 0
    finally:
        conn.close()

# Получение активности
def get_activity_by_range(range_type):
    try:
        conn = sqlite3.connect(DB_PATH)
        query = """
            SELECT strftime('%H', first_seen) as hour, COUNT(*) as activity_count
            FROM users
            WHERE first_seen >= ?
            GROUP BY hour
            ORDER BY hour
        """
        if range_type == "day":
            start_time = datetime.now() - timedelta(days=1)
        elif range_type == "week":
            start_time = datetime.now() - timedelta(days=7)
        elif range_type == "month":
            start_time = datetime.now() - timedelta(days=30)
        else:
            start_time = datetime.now() - timedelta(days=1)
        df = pd.read_sql_query(query, conn, params=(start_time,))
        return df
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения активности: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

# Генерация ASCII-графика
def generate_ascii_chart(range_type):
    df = get_activity_by_range(range_type)
    if df.empty:
        logger.warning(f"Нет данных для графика ({range_type})")
        return "Нет данных для графика"

    activity_counts = [0] * 24
    for _, row in df.iterrows():
        hour = int(row['hour'])
        activity_counts[hour] = row['activity_count']

    chart = plot(activity_counts, {'height': 10, 'format': '{:8.0f}'})
    return f"Активность ({range_type}):\n{chart}"

# Flask: Главная страница
@app.route('/')
async def stats_page():
    logger.info("Запрос к главной странице")
    active_users, banned_users, active_configs, total_configs = get_stats()
    ascii_chart_day = generate_ascii_chart("day")
    api_status_ok, api_status_message = await check_telegram_api()
    return render_template_string(
        """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>WARP Bot Dashboard</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-gray-900 text-gray-100">
            <nav class="bg-gray-800 p-4 shadow">
                <div class="container mx-auto flex justify-between items-center">
                    <h1 class="text-2xl font-bold">WARP Bot Dashboard</h1>
                    <div>
                        <a href="/" class="text-gray-300 hover:text-white px-3 py-2 rounded">Главная</a>
                        <a href="/activity/day" class="text-gray-300 hover:text-white px-3 py-2 rounded">24 часа</a>
                        <a href="/activity/week" class="text-gray-300 hover:text-white px-3 py-2 rounded">Неделя</a>
                        <a href="/activity/month" class="text-gray-300 hover:text-white px-3 py-2 rounded">Месяц</a>
                    </div>
                </div>
            </nav>
            <div class="container mx-auto p-6">
                <h2 class="text-3xl font-semibold mb-6">Статистика</h2>
                <div class="bg-gray-800 p-4 rounded-lg mb-6">
                    <p class="text-lg font-medium">
                        Статус Telegram API: 
                        <span class="{% if api_status_ok %}text-green-400{% else %}text-red-400{% endif %} font-bold">
                            {{ api_status_message }}
                        </span>
                    </p>
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                    <div class="bg-gray-800 p-6 rounded-lg shadow">
                        <h3 class="text-lg font-medium text-gray-300">Активные пользователи</h3>
                        <p class="text-2xl font-bold text-blue-400">{{ active_users }}</p>
                    </div>
                    <div class="bg-gray-800 p-6 rounded-lg shadow">
                        <h3 class="text-lg font-medium text-gray-300">Забаненные пользователи</h3>
                        <p class="text-2xl font-bold text-red-400">{{ banned_users }}</p>
                    </div>
                    <div class="bg-gray-800 p-6 rounded-lg shadow">
                        <h3 class="text-lg font-medium text-gray-300">Активные конфигурации</h3>
                        <p class="text-2xl font-bold text-green-400">{{ active_configs }}</p>
                    </div>
                    <div class="bg-gray-800 p-6 rounded-lg shadow">
                        <h3 class="text-lg font-medium text-gray-300">Всего конфигураций</h3>
                        <p class="text-2xl font-bold text-purple-400">{{ total_configs }}</p>
                    </div>
                </div>
                <h2 class="text-3xl font-semibold mb-6">Активность пользователей</h2>
                <div class="bg-gray-800 p-6 rounded-lg shadow">
                    <h3 class="text-xl font-medium mb-4">График активности (24 часа)</h3>
                    <pre class="font-mono text-sm bg-gray-900 p-4 rounded">{{ ascii_chart_day }}</pre>
                    <div class="mt-4 flex space-x-4">
                        <a href="/activity/day" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">24 часа</a>
                        <a href="/activity/week" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">Неделя</a>
                        <a href="/activity/month" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">Месяц</a>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """,
        active_users=active_users,
        banned_users=banned_users,
        active_configs=active_configs,
        total_configs=total_configs,
        ascii_chart_day=ascii_chart_day,
        api_status_ok=api_status_ok,
        api_status_message=api_status_message
    )

# Flask: График активности
@app.route('/activity/<range_type>')
async def activity_plot(range_type):
    logger.info(f"Запрос к графику активности ({range_type})")
    if range_type not in ["day", "week", "month"]:
        return "Недопустимый диапазон", 400
    ascii_chart = generate_ascii_chart(range_type)
    api_status_ok, api_status_message = await check_telegram_api()
    return render_template_string(
        """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>WARP Bot Activity</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-gray-900 text-gray-100">
            <nav class="bg-gray-800 p-4 shadow">
                <div class="container mx-auto flex justify-between items-center">
                    <h1 class="text-2xl font-bold">WARP Bot Dashboard</h1>
                    <div>
                        <a href="/" class="text-gray-300 hover:text-white px-3 py-2 rounded">Главная</a>
                        <a href="/activity/day" class="text-gray-300 hover:text-white px-3 py-2 rounded">24 часа</a>
                        <a href="/activity/week" class="text-gray-300 hover:text-white px-3 py-2 rounded">Неделя</a>
                        <a href="/activity/month" class="text-gray-300 hover:text-white px-3 py-2 rounded">Месяц</a>
                    </div>
                </div>
            </nav>
            <div class="container mx-auto p-6">
                <h2 class="text-3xl font-semibold mb-6">Активность пользователей ({{ range_type }})</h2>
                <div class="bg-gray-800 p-4 rounded-lg mb-6">
                    <p class="text-lg font-medium">
                        Статус Telegram API: 
                        <span class="{% if api_status_ok %}text-green-400{% else %}text-red-400{% endif %} font-bold">
                            {{ api_status_message }}
                        </span>
                    </p>
                </div>
                <div class="bg-gray-800 p-6 rounded-lg shadow">
                    <pre class="font-mono text-sm bg-gray-900 p-4 rounded">{{ ascii_chart }}</pre>
                    <div class="mt-4 flex space-x-4">
                        <a href="/activity/day" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">24 часа</a>
                        <a href="/activity/week" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">Неделя</a>
                        <a href="/activity/month" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">Месяц</a>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """,
        range_type=range_type,
        ascii_chart=ascii_chart,
        api_status_ok=api_status_ok,
        api_status_message=api_status_message
    )

# Клавиатура бота
def get_main_keyboard(is_admin_user=False):
    keyboard = [
        [
            InlineKeyboardButton("Получить конфиг", callback_data="get_config"),
            InlineKeyboardButton("Справка", callback_data="help"),
        ],
        [
            InlineKeyboardButton("XrayVPN", url="https://astracat2022.github.io/vpngen/generator"),
        ]
    ]
    if is_admin_user:
        keyboard.append([
            InlineKeyboardButton("Статистика", callback_data="stats"),
            InlineKeyboardButton("Пользователи", callback_data="users"),
        ])
        keyboard.append([
            InlineKeyboardButton("Активность (24ч)", callback_data="activity_day"),
            InlineKeyboardButton("Активность (неделя)", callback_data="activity_week"),
        ])
        keyboard.append([
            InlineKeyboardButton("Активность (месяц)", callback_data="activity_month"),
        ])
    return InlineKeyboardMarkup(keyboard)

# Обработчик /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO users (telegram_id, username, first_name, last_name, first_seen, is_banned) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user.id, user.username, user.first_name, user.last_name, datetime.now(), 0)
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Ошибка записи пользователя: {e}")
    finally:
        conn.close()

    is_admin_user = is_admin(user.id)
    reply_markup = get_main_keyboard(is_admin_user)
    await update.message.reply_text(
        f"Добро пожаловать, {user.first_name or 'пользователь'}! 👋\n"
        f"ID: {user.id}\n"
        "Бот для WARP конфигураций. Выберите действие:",
        reply_markup=reply_markup
    )

# Обработчик кнопок
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    is_admin_user = is_admin(user.id)
    reply_markup = get_main_keyboard(is_admin_user)
    await query.answer()

    if query.data == "get_config":
        await get_config(update, context)
    elif query.data == "help":
        help_text = (
            "Бот для WARP конфигураций. Команды:\n"
            "/start - Начать\n"
            "/getconfig - Получить WARP конфиг\n"
            "Админ-команды:\n"
            "/stats - Статистика\n"
            "/users - Пользователи\n"
            "/ban <id> - Забанить\n"
            "/unban <id> - Разбанить\n"
            "/broadcast <текст> - Рассылка\n"
            "/hourly_activity - График активности"
        )
        await query.message.reply_text(help_text, reply_markup=reply_markup)
    elif query.data == "stats" and is_admin_user:
        await stats(update, context)
    elif query.data == "users" and is_admin_user:
        await users(update, context)
    elif query.data in ["activity_day", "activity_week", "activity_month"] and is_admin_user:
        range_type = {"activity_day": "day", "activity_week": "week", "activity_month": "month"}[query.data]
        ascii_chart = generate_ascii_chart(range_type)
        await query.message.reply_text(
            f"Активность ({range_type}):\n```\n{ascii_chart}\n```",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

# Обработчик /getconfig
async def get_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT is_banned, last_config_time FROM users WHERE telegram_id = ?", (user.id,))
    result = c.fetchone()
    if result and result[0] == 1:
        await update.message.reply_text("Вы забанены", reply_markup=get_main_keyboard())
        conn.close()
        return

    if result and result[1]:
        last_time = datetime.fromisoformat(result[1])
        if datetime.now() - last_time < timedelta(hours=24):
            await update.message.reply_text(
                "Конфиг можно запрашивать раз в 24 часа",
                reply_markup=get_main_keyboard()
            )
            conn.close()
            return

    config = generate_warp_config()
    config_id = str(uuid.uuid4())
    c.execute(
        "INSERT INTO configs (config_id, telegram_id, created_at, is_active) VALUES (?, ?, ?, ?)",
        (config_id, user.id, datetime.now(), 1)
    )
    c.execute(
        "UPDATE users SET last_config_time = ? WHERE telegram_id = ?",
        (datetime.now().isoformat(), user.id)
    )
    conn.commit()
    conn.close()

    config_path = f"/tmp/config_{user.id}.conf"
    with open(config_path, "w") as f:
        f.write(config)
    try:
        with open(config_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="warp.conf",
                caption="Ваша WARP конфигурация",
                reply_markup=get_main_keyboard(is_admin(user.id))
            )
    finally:
        if os.path.exists(config_path):
            os.remove(config_path)

# Обработчик /stats
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Только для админа")
        return
    active_users, banned_users, active_configs, total_configs = get_stats()
    stats_message = (
        f"📊 Статистика:\n"
        f"Активные пользователи: {active_users}\n"
        f"Забаненные: {banned_users}\n"
        f"Активные конфиги: {active_configs}\n"
        f"Всего конфигов: {total_configs}"
    )
    await update.message.reply_text(stats_message, reply_markup=get_main_keyboard(is_admin=True))

# Обработчик /users
async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Только для админа")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT telegram_id, username, first_name, is_banned FROM users")
    users = c.fetchall()
    conn.close()
    users_message = "👥 Пользователи:\n\n"
    for user in users:
        status = "🚫 Забанен" if user[3] else "✅ Активен"
        users_message += f"ID: {user[0]}\nUsername: {user[1] or 'N/A'}\nИмя: {user[2]}\nСтатус: {status}\n\n"
    await update.message.reply_text(users_message, reply_markup=get_main_keyboard(is_admin=True))

# Обработчик /ban
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Только для админа")
        return
    if not context.args:
        await update.message.reply_text("Укажите ID: /ban <telegram_id>")
        return
    try:
        target_id = int(context.args[0])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned = 1 WHERE telegram_id = ?", (target_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Пользователь {target_id} забанен", reply_markup=get_main_keyboard(is_admin=True))
        try:
            await context.bot.send_message(chat_id=target_id, text="Вы забанены")
        except Exception as e:
            logger.warning(f"Не удалось уведомить ID {target_id}: {e}")
    except ValueError:
        await update.message.reply_text("Неверный ID", reply_markup=get_main_keyboard(is_admin=True))

# Обработчик /unban
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Только для админа")
        return
    if not context.args:
        await update.message.reply_text("Укажите ID: /unban <telegram_id>")
        return
    try:
        target_id = int(context.args[0])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned = 0 WHERE telegram_id = ?", (target_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Пользователь {target_id} разбанен", reply_markup=get_main_keyboard(is_admin=True))
        try:
            await context.bot.send_message(chat_id=target_id, text="Вы разбанены")
        except Exception as e:
            logger.warning(f"Не удалось уведомить ID {target_id}: {e}")
    except ValueError:
        await update.message.reply_text("Неверный ID", reply_markup=get_main_keyboard(is_admin=True))

# Обработчик /broadcast
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Только для админа")
        return
    if not context.args:
        await update.message.reply_text("Укажите сообщение: /broadcast <текст>")
        return
    message = " ".join(context.args)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT telegram_id FROM users WHERE is_banned = 0")
    users = c.fetchall()
    conn.close()
    success_count = 0
    for user in users:
        try:
            await context.bot.send_message(chat_id=user[0], text=message)
            success_count += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение ID {user[0]}: {e}")
    await update.message.reply_text(
        f"Рассылка завершена. Отправлено {success_count} пользователям",
        reply_markup=get_main_keyboard(is_admin=True)
    )

# Обработчик /hourly_activity
async def hourly_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Только для админа")
        return
    ascii_chart = generate_ascii_chart("day")
    await update.message.reply_text(
        f"Активность (24 часа):\n```\n{ascii_chart}\n```",
        reply_markup=get_main_keyboard(is_admin=True),
        parse_mode="Markdown"
    )

# Обработчик ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")

# Запуск бота
async def run_bot():
    global application
    logger.info("Создание Application")
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(CommandHandler("getconfig", get_config))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("users", users))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("hourly_activity", hourly_activity))
    application.add_error_handler(error_handler)
    logger.info("Обработчики зарегистрированы")

    logger.info("Запуск polling")
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        await application.initialize()
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Polling запущен")
    except Exception as e:
        logger.error(f"Ошибка polling: {e}")
        raise

# Главная функция
def main():
    logger.info("Запуск приложения")
    init_db()

    try:
        bot_thread = threading.Thread(target=lambda: asyncio.run(run_bot()))
        bot_thread.daemon = True
        bot_thread.start()
        logger.info("Бот запущен в режиме polling")
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
        raise

    app.run(host='0.0.0.0', port=int(PORT))

if __name__ == "__main__":
    main()
