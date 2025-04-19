import sqlite3
import os
import logging
import asyncio
import uuid
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import Conflict, NetworkError, TelegramError
from datetime import datetime, timedelta
import pandas as pd
from flask import Flask, render_template_string, request
from asciichartpy import plot
import aiohttp

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")
PORT = os.getenv("PORT", "5000")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "warpxc.onrender.com")

logger.info(f"Загруженные переменные: BOT_TOKEN={'***' if BOT_TOKEN else 'не задан'}, "
            f"ADMIN_TELEGRAM_ID={ADMIN_TELEGRAM_ID or 'не задан'}, "
            f"PORT={PORT}, RENDER_EXTERNAL_HOSTNAME={RENDER_EXTERNAL_HOSTNAME}")

if not BOT_TOKEN:
    logger.error("Переменная окружения BOT_TOKEN не задана.")
    raise ValueError("Ошибка: Переменная окружения BOT_TOKEN не задана.")
if not ADMIN_TELEGRAM_ID:
    logger.error("Переменная окружения ADMIN_TELEGRAM_ID не задана.")
    raise ValueError("Ошибка: Переменная окружения ADMIN_TELEGRAM_ID не задана.")

try:
    ADMIN_TELEGRAM_ID = int(ADMIN_TELEGRAM_ID)
except ValueError:
    logger.error("ADMIN_TELEGRAM_ID должен быть числом.")
    raise ValueError("Ошибка: ADMIN_TELEGRAM_ID должен быть числом.")

# Инициализация Flask
app = Flask(__name__)
application = None  # Глобальная переменная для Telegram Application

# Проверка связи с Telegram API
async def check_telegram_api():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe") as response:
                data = await response.json()
                if data.get("ok"):
                    logger.info("Связь с Telegram API активна.")
                    return True, "🟢 Активна"
                else:
                    logger.warning(f"Ошибка Telegram API: {data}")
                    return False, f"🔴 Отсутствует ({data.get('description', 'Неизвестная ошибка')})"
    except Exception as e:
        logger.error(f"Ошибка проверки Telegram API: {e}")
        return False, f"🔴 Отсутствует ({str(e)})"

# Инициализация базы данных
def init_db():
    try:
        conn = sqlite3.connect("warp_bot.db")
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            first_seen DATETIME,
            last_config_time TEXT,
            is_banned INTEGER DEFAULT 0
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS configs (
            config_id TEXT PRIMARY KEY,
            telegram_id INTEGER,
            created_at DATETIME,
            is_active INTEGER DEFAULT 1,
            FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
        )''')
        conn.commit()
        logger.info("База данных инициализирована успешно.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")
        raise
    finally:
        conn.close()

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
H3 = 3
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

# Проверка, является ли пользователь админом
def is_admin(telegram_id):
    return telegram_id == ADMIN_TELEGRAM_ID

# Получение статистики
def get_stats():
    try:
        conn = sqlite3.connect("warp_bot.db")
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

# Получение активности по диапазонам времени
def get_activity_by_range(range_type):
    try:
        conn = sqlite3.connect("warp_bot.db")
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
        logger.error(f"Ошибка получения данных активности: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

# Генерация текстового графика
def generate_ascii_chart(range_type):
    df = get_activity_by_range(range_type)
    if df.empty:
        logger.warning(f"Нет данных для графика активности ({range_type}).")
        return "Нет данных для отображения графика."

    # Заполняем массив для 24 часов
    activity_counts = [0] * 24
    for _, row in df.iterrows():
        hour = int(row['hour'])
        activity_counts[hour] = row['activity_count']

    # Генерируем ASCII-график
    chart = plot(activity_counts, {'height': 10, 'format': '{:8.0f}'})
    return f"Активность пользователей ({range_type}):\n{chart}"

# Flask маршрут для главной страницы
@app.route('/')
async def stats_page():
    logger.info("Запрос к главной странице статистики")
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
                        Связь с Telegram API: 
                        <span class="{% if api_status_ok %}text-green-400{% else %}text-red-400{% endif %}">
                            {{ api_status_message }}
                        </span>
                    </p>
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                    <div class="bg-gray-800 p-6 rounded-lg shadow hover:shadow-lg transition">
                        <h3 class="text-lg font-medium text-gray-300">Активные пользователи</h3>
                        <p class="text-2xl font-bold text-blue-400">{{ active_users }}</p>
                    </div>
                    <div class="bg-gray-800 p-6 rounded-lg shadow hover:shadow-lg transition">
                        <h3 class="text-lg font-medium text-gray-300">Забаненные пользователи</h3>
                        <p class="text-2xl font-bold text-red-400">{{ banned_users }}</p>
                    </div>
                    <div class="bg-gray-800 p-6 rounded-lg shadow hover:shadow-lg transition">
                        <h3 class="text-lg font-medium text-gray-300">Активные конфигурации</h3>
                        <p class="text-2xl font-bold text-green-400">{{ active_configs }}</p>
                    </div>
                    <div class="bg-gray-800 p-6 rounded-lg shadow hover:shadow-lg transition">
                        <h3 class="text-lg font-medium text-gray-300">Всего конфигураций</h3>
                        <p class="text-2xl font-bold text-purple-400">{{ total_configs }}</p>
                    </div>
                </div>
                <h2 class="text-3xl font-semibold mb-6">Активность пользователей</h2>
                <div class="bg-gray-800 p-6 rounded-lg shadow">
                    <h3 class="text-xl font-medium mb-4">График активности (последние 24 часа)</h3>
                    <pre class="font-mono text-sm bg-gray-900 p-4 rounded">{{ ascii_chart_day }}</pre>
                    <div class="mt-4 flex space-x-4">
                        <a href="/activity/day" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 transition">24 часа</a>
                        <a href="/activity/week" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 transition">Неделя</a>
                        <a href="/activity/month" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 transition">Месяц</a>
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

# Flask маршрут для графика активности
@app.route('/activity/<range_type>')
async def activity_plot(range_type):
    logger.info(f"Запрос к графику активности ({range_type})")
    if range_type not in ["day", "week", "month"]:
        return "Недопустимый диапазон времени.", 400
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
                        Связь с Telegram API: 
                        <span class="{% if api_status_ok %}text-green-400{% else %}text-red-400{% endif %}">
                            {{ api_status_message }}
                        </span>
                    </p>
                </div>
                <div class="bg-gray-800 p-6 rounded-lg shadow">
                    <pre class="font-mono text-sm bg-gray-900 p-4 rounded">{{ ascii_chart }}</pre>
                    <div class="mt-4 flex space-x-4">
                        <a href="/activity/day" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 transition">24 часа</a>
                        <a href="/activity/week" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 transition">Неделя</a>
                        <a href="/activity/month" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 transition">Месяц</a>
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

# Flask маршрут для webhook
@app.route('/webhook', methods=['POST'])
async def webhook():
    try:
        update = Update.de_json(request.get_json(), application.bot)
        await application.process_update(update)
        return '', 200
    except Exception as e:
        logger.error(f"Ошибка обработки webhook: {e}")
        return '', 500

# Создание клавиатуры с кнопками
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

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect("warp_bot.db")
    c = conn.cursor()
    
    # Регистрация пользователя
    c.execute(
        "INSERT OR REPLACE INTO users (telegram_id, username, first_name, last_name, first_seen, last_config_time, is_banned) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user.id, user.username, user.first_name, user.last_name, datetime.now(), None, 0)
    )
    conn.commit()
    conn.close()
    
    is_admin_user = is_admin(user.id)
    reply_markup = get_main_keyboard(is_admin_user)
    await update.message.reply_text(
        f"Добро пожаловать, {user.first_name or 'пользователь'}! 👋\n"
        f"Ваш Telegram ID: {user.id}\n"
        "Я бот для управления WARP конфигурациями. Выберите действие:",
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
            "Я бот для управления WARP конфигурациями. Доступные команды:\n"
            "/start - Начать работу\n"
            "/getconfig - Получить конфигурацию WARP (.conf файл)\n"
            "Для админов:\n"
            "/stats - Статистика\n"
            "/users - Список пользователей\n"
            "/ban <user_id> - Забанить\n"
            "/unban <user_id> - Разбанить\n"
            "/broadcast <сообщение> - Рассылка\n"
            "/hourly_activity - График активности\n"
            "Используйте кнопки для удобства!"
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
            f"Активность пользователей ({range_type}):\n```\n{ascii_chart}\n```",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

# Обработчик команды /getconfig
async def get_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect("warp_bot.db")
    c = conn.cursor()
    
    # Проверка на бан
    c.execute("SELECT is_banned FROM users WHERE telegram_id = ?", (user.id,))
    result = c.fetchone()
    if result and result[0] == 1:
        await update.message.reply_text("Вы забанены и не можете получать конфигурации.", reply_markup=get_main_keyboard())
        conn.close()
        return
    
    # Проверка времени последнего запроса (лимит 1 конфиг в 24 часа)
    c.execute("SELECT last_config_time FROM users WHERE telegram_id = ?", (user.id,))
    last_config_time = c.fetchone()[0]
    if last_config_time:
        last_time = datetime.fromisoformat(last_config_time)
        if datetime.now() - last_time < timedelta(hours=24):
            await update.message.reply_text(
                "Вы можете запрашивать новую конфигурацию раз в 24 часа. Попробуйте позже.",
                reply_markup=get_main_keyboard()
            )
            conn.close()
            return
    
    # Генерация и сохранение конфигурации
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
    
    # Отправка конфигурации
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

# Обработчик команды /stats
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return
    
    active_users, banned_users, active_configs, total_configs = get_stats()
    stats_message = (
        f"📊 Статистика бота:\n"
        f"Активных пользователей: {active_users}\n"
        f"Забаненных пользователей: {banned_users}\n"
        f"Активных конфигураций: {active_configs}\n"
        f"Всего выдано конфигураций: {total_configs}"
    )
    await update.message.reply_text(stats_message, reply_markup=get_main_keyboard(is_admin=True))

# Обработчик команды /users
async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return
    
    conn = sqlite3.connect("warp_bot.db")
    c = conn.cursor()
    c.execute("SELECT telegram_id, username, first_name, last_name, is_banned FROM users")
    users = c.fetchall()
    conn.close()
    
    users_message = "👥 Список пользователей:\n\n"
    for user in users:
        status = "🚫 Забанен" if user[4] == 1 else "✅ Активен"
        users_message += (
            f"ID: {user[0]}\n"
            f"Username: {user[1] or 'N/A'}\n"
            f"Имя: {user[2]} {user[3] or ''}\n"
            f"Статус: {status}\n\n"
        )
    
    await update.message.reply_text(users_message, reply_markup=get_main_keyboard(is_admin=True))

# Обработчик команды /ban
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return
    
    if not context.args:
        await update.message.reply_text("Укажите Telegram ID: /ban <telegram_id>")
        return
    
    try:
        target_id = int(context.args[0])
        conn = sqlite3.connect("warp_bot.db")
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned = 1 WHERE telegram_id = ?", (target_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Пользователь {target_id} забанен.", reply_markup=get_main_keyboard(is_admin=True))
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="Вы были забанены администратором."
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить пользователя ID {target_id}: {e}")
    except ValueError:
        await update.message.reply_text("Неверный формат Telegram ID.", reply_markup=get_main_keyboard(is_admin=True))

# Обработчик команды /unban
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return
    
    if not context.args:
        await update.message.reply_text("Укажите Telegram ID: /unban <telegram_id>")
        return
    
    try:
        target_id = int(context.args[0])
        conn = sqlite3.connect("warp_bot.db")
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned = 0 WHERE telegram_id = ?", (target_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Пользователь {target_id} разбанен.", reply_markup=get_main_keyboard(is_admin=True))
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="Вы были разбанены администратором."
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить пользователя ID {target_id}: {e}")
    except ValueError:
        await update.message.reply_text("Неверный формат Telegram ID.", reply_markup=get_main_keyboard(is_admin=True))

# Обработчик команды /broadcast
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return
    
    if not context.args:
        await update.message.reply_text("Укажите сообщение: /broadcast <сообщение>")
        return
    
    message = " ".join(context.args)
    conn = sqlite3.connect("warp_bot.db")
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
            logger.warning(f"Не удалось отправить сообщение пользователю ID {user[0]}: {e}")
    
    await update.message.reply_text(
        f"Рассылка завершена. Сообщение отправлено {success_count} пользователям.",
        reply_markup=get_main_keyboard(is_admin=True)
    )

# Обработчик команды /hourly_activity
async def hourly_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return
    
    ascii_chart = generate_ascii_chart("day")
    reply_markup = get_main_keyboard(is_admin=True)
    await update.message.reply_text(
        f"Активность пользователей (24 часа):\n```\n{ascii_chart}\n```",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Обработчик ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

# Установка webhook
async def set_webhook():
    global application
    logger.info("Инициализация базы данных...")
    init_db()
    logger.info("Создание Application builder...")
    application = Application.builder().token(BOT_TOKEN).build()
    logger.info("Application builder создан успешно.")

    # Регистрация обработчиков
    logger.info("Регистрация обработчиков команд...")
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
    logger.info("Обработчики команд зарегистрированы.")

    webhook_url = f"https://{RENDER_EXTERNAL_HOSTNAME}/webhook"
    logger.info(f"Установка webhook: {webhook_url}")
    max_retries = 3
    retry_delay = 5
    for attempt in range(max_retries):
        try:
            await application.bot.delete_webhook(drop_pending_updates=True)
            await application.bot.set_webhook(webhook_url)
            logger.info("Webhook успешно установлен.")
            return
        except TelegramError as e:
            logger.error(f"Ошибка установки webhook (попытка {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
            else:
                raise
        except Exception as e:
            logger.error(f"Неизвестная ошибка при установке webhook: {e}")
            raise

# Запуск Flask и Telegram-бота
def main():
    logger.info("Запуск приложения...")
    try:
        asyncio.run(set_webhook())
        logger.info("Webhook-режим активирован.")
    except Exception as e:
        logger.error(f"Критическая ошибка при установке webhook: {e}")
        raise

    # Запускаем Flask (gunicorn используется на Render)
    app.run(host='0.0.0.0', port=int(PORT))

if __name__ == "__main__":
    main()
