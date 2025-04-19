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
    MessageHandler,
    filters
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
BOT_TOKEN = os.getenv("BOT_TOKEN", "7935425343:AAECbjFJvLHkeTvwHAKDG8uvmy-KiWcPtns")
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", 650154766))
PORT = int(os.getenv("PORT", "5000"))
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "warpxc.onrender.com")

logger.info("Конфигурация загружена")

# Инициализация Flask
app = Flask(__name__)
application = None  # Глобальная переменная для Telegram Application

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect("warp_bot.db", check_same_thread=False)
    cursor = conn.cursor()
    
    # Создаем таблицу пользователей, если она не существует
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        first_seen DATETIME,
        last_config_time DATETIME,
        is_banned INTEGER DEFAULT 0
    )
    ''')
    
    # Создаем таблицу конфигов, если она не существует
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS configs (
        config_id TEXT PRIMARY KEY,
        telegram_id INTEGER,
        created_at DATETIME,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
    )
    ''')
    
    conn.commit()
    logger.info("База данных инициализирована")
    return conn

# Глобальное соединение с базой данных
global_conn = init_db()

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

# Генерация WARP конфигурации
def generate_warp_config():
    private_key = f"CS/UQwV5cCjhGdH/1FQbSkRLvYU8Ha1xeTkHVg5rizI={uuid.uuid4().hex[:8]}"
    public_key = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="
    config = f"""[Interface]
PrivateKey = {private_key}
Address = 172.16.0.2/32, 2606:4700:110:8a82:ae4c:ce7e:e5a6:a7fd/128
DNS = 1.1.1.1, 1.0.0.1, 2606:4700:4700::1111, 2606:4700:4700::1001
MTU = 1280

[Peer]
PublicKey = {public_key}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = 162.159.192.227:894
PersistentKeepalive = 25
"""
    return config

# Проверка админ-прав
def is_admin(telegram_id):
    return telegram_id == ADMIN_TELEGRAM_ID

# Получение статистики
def get_stats():
    try:
        c = global_conn.cursor()
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

# Получение активности
def get_activity_by_range(range_type):
    try:
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
            
        df = pd.read_sql_query(query, global_conn, params=(start_time,))
        return df
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения активности: {e}")
        return pd.DataFrame()

# Генерация ASCII-графика
def generate_ascii_chart(range_type):
    df = get_activity_by_range(range_type)
    if df.empty:
        return "Нет данных для графика"

    activity_counts = [0] * 24
    for _, row in df.iterrows():
        hour = int(row['hour'])
        activity_counts[hour] = row['activity_count']

    chart = plot(activity_counts, {'height': 10, 'format': '{:8.0f}'})
    return f"Активность ({range_type}):\n{chart}"

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
    logger.info(f"Новый пользователь: {user.id}")
    
    try:
        c = global_conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO users (telegram_id, username, first_name, last_name, first_seen) "
            "VALUES (?, ?, ?, ?, ?)",
            (user.id, user.username, user.first_name, user.last_name, datetime.now())
        )
        global_conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Ошибка записи пользователя: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")
        return

    is_admin_user = is_admin(user.id)
    reply_markup = get_main_keyboard(is_admin_user)
    
    await update.message.reply_text(
        f"Привет, {user.first_name or 'пользователь'}! 👋\n"
        "Я бот для генерации WARP конфигураций. Выберите действие:",
        reply_markup=reply_markup
    )

# Обработчик кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    is_admin_user = is_admin(user.id)
    
    if query.data == "get_config":
        await get_config(update, context)
    elif query.data == "help":
        help_text = (
            "📚 Справка по боту:\n\n"
            "Этот бот генерирует конфигурации для WARP.\n\n"
            "Основные команды:\n"
            "/start - Начать работу с ботом\n"
            "/getconfig - Получить конфигурацию\n\n"
            "Конфигурацию можно запрашивать раз в 24 часа."
        )
        await query.edit_message_text(help_text, reply_markup=get_main_keyboard(is_admin_user))
    elif query.data == "stats" and is_admin_user:
        await stats_command(update, context)
    elif query.data == "users" and is_admin_user:
        await users_command(update, context)
    elif query.data.startswith("activity_") and is_admin_user:
        range_type = query.data.split("_")[1]
        ascii_chart = generate_ascii_chart(range_type)
        await query.edit_message_text(
            f"Активность ({range_type}):\n```\n{ascii_chart}\n```",
            reply_markup=get_main_keyboard(is_admin_user),
            parse_mode="Markdown"
        )

# Обработчик /getconfig
async def get_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Запрос конфига от пользователя {user.id}")
    
    try:
        c = global_conn.cursor()
        
        # Проверка бана
        c.execute("SELECT is_banned FROM users WHERE telegram_id = ?", (user.id,))
        result = c.fetchone()
        if result and result[0] == 1:
            await update.message.reply_text("❌ Вы забанены и не можете получать конфигурации.")
            return
        
        # Проверка времени последнего запроса
        c.execute("SELECT last_config_time FROM users WHERE telegram_id = ?", (user.id,))
        result = c.fetchone()
        if result and result[0]:
            last_time = datetime.fromisoformat(result[0])
            if datetime.now() - last_time < timedelta(hours=24):
                wait_time = 24 - (datetime.now() - last_time).total_seconds() / 3600
                await update.message.reply_text(
                    f"⏳ Вы можете запрашивать конфигурацию раз в 24 часа. "
                    f"Попробуйте снова через {wait_time:.1f} часов."
                )
                return
        
        # Генерация конфига
        config = generate_warp_config()
        config_id = str(uuid.uuid4())
        
        # Сохранение в БД
        c.execute(
            "INSERT INTO configs (config_id, telegram_id, created_at) VALUES (?, ?, ?)",
            (config_id, user.id, datetime.now())
        )
        c.execute(
            "UPDATE users SET last_config_time = ? WHERE telegram_id = ?",
            (datetime.now().isoformat(), user.id)
        )
        global_conn.commit()
        
        # Отправка конфига
        with open("warp.conf", "w") as f:
            f.write(config)
        
        with open("warp.conf", "rb") as f:
            await context.bot.send_document(
                chat_id=user.id,
                document=f,
                filename="warp.conf",
                caption="Ваша WARP конфигурация"
            )
        
        os.remove("warp.conf")
        logger.info(f"Конфиг отправлен пользователю {user.id}")
        
    except Exception as e:
        logger.error(f"Ошибка при генерации конфига: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")

# Обработчик /stats
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда только для администратора.")
        return
    
    active_users, banned_users, active_configs, total_configs = get_stats()
    response = (
        "📊 Статистика бота:\n\n"
        f"👥 Пользователи: {active_users} активных, {banned_users} забаненных\n"
        f"📂 Конфигурации: {active_configs} активных, {total_configs} всего\n\n"
        "Используйте кнопки ниже для просмотра активности:"
    )
    
    await update.message.reply_text(
        response,
        reply_markup=get_main_keyboard(is_admin=True)
    )

# Обработчик /users
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда только для администратора.")
        return
    
    try:
        c = global_conn.cursor()
        c.execute("SELECT telegram_id, username, first_name, is_banned FROM users ORDER BY first_seen DESC LIMIT 50")
        users = c.fetchall()
        
        if not users:
            await update.message.reply_text("Нет пользователей в базе данных.")
            return
        
        response = "👥 Последние 50 пользователей:\n\n"
        for user in users:
            status = "🚫" if user[3] else "✅"
            response += f"{status} ID: {user[0]}, Username: @{user[1]}, Имя: {user[2]}\n"
        
        await update.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Ошибка при получении списка пользователей: {e}")
        await update.message.reply_text("Произошла ошибка при получении списка пользователей.")

# Обработчик /ban
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда только для администратора.")
        return
    
    if not context.args:
        await update.message.reply_text("Использование: /ban <user_id>")
        return
    
    try:
        user_id = int(context.args[0])
        c = global_conn.cursor()
        
        # Проверяем, есть ли пользователь
        c.execute("SELECT 1 FROM users WHERE telegram_id = ?", (user_id,))
        if not c.fetchone():
            await update.message.reply_text("Пользователь не найден.")
            return
        
        # Баним
        c.execute("UPDATE users SET is_banned = 1 WHERE telegram_id = ?", (user_id,))
        global_conn.commit()
        
        await update.message.reply_text(f"Пользователь {user_id} забанен.")
        
        # Пытаемся уведомить пользователя
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="⛔ Вы были забанены администратором."
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить пользователя {user_id}: {e}")
            
    except ValueError:
        await update.message.reply_text("Неверный ID пользователя.")
    except Exception as e:
        logger.error(f"Ошибка при бане пользователя: {e}")
        await update.message.reply_text("Произошла ошибка при выполнении команды.")

# Обработчик /unban
async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда только для администратора.")
        return
    
    if not context.args:
        await update.message.reply_text("Использование: /unban <user_id>")
        return
    
    try:
        user_id = int(context.args[0])
        c = global_conn.cursor()
        
        # Проверяем, есть ли пользователь
        c.execute("SELECT 1 FROM users WHERE telegram_id = ?", (user_id,))
        if not c.fetchone():
            await update.message.reply_text("Пользователь не найден.")
            return
        
        # Разбаниваем
        c.execute("UPDATE users SET is_banned = 0 WHERE telegram_id = ?", (user_id,))
        global_conn.commit()
        
        await update.message.reply_text(f"Пользователь {user_id} разбанен.")
        
        # Пытаемся уведомить пользователя
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ Вы были разбанены администратором."
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить пользователя {user_id}: {e}")
            
    except ValueError:
        await update.message.reply_text("Неверный ID пользователя.")
    except Exception as e:
        logger.error(f"Ошибка при разбане пользователя: {e}")
        await update.message.reply_text("Произошла ошибка при выполнении команды.")

# Обработчик /broadcast
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда только для администратора.")
        return
    
    if not context.args:
        await update.message.reply_text("Использование: /broadcast <сообщение>")
        return
    
    message = " ".join(context.args)
    c = global_conn.cursor()
    c.execute("SELECT telegram_id FROM users WHERE is_banned = 0")
    users = c.fetchall()
    
    if not users:
        await update.message.reply_text("Нет активных пользователей для рассылки.")
        return
    
    success = 0
    failed = 0
    
    await update.message.reply_text(f"Начинаю рассылку для {len(users)} пользователей...")
    
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user[0],
                text=f"📢 Сообщение от администратора:\n\n{message}"
            )
            success += 1
        except Exception as e:
            failed += 1
            logger.warning(f"Не удалось отправить сообщение пользователю {user[0]}: {e}")
        
        # Небольшая задержка, чтобы не превысить лимиты Telegram
        await asyncio.sleep(0.1)
    
    await update.message.reply_text(
        f"Рассылка завершена:\n"
        f"✅ Успешно: {success}\n"
        f"❌ Не удалось: {failed}"
    )

# Обработчик ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)
    if update and update.effective_message:
        await update.effective_message.reply_text("Произошла ошибка. Пожалуйста, попробуйте позже.")

# Flask: Главная страница
@app.route('/')
async def stats_page():
    active_users, banned_users, active_configs, total_configs = get_stats()
    ascii_chart_day = generate_ascii_chart("day")
    api_status_ok, api_status_message = await check_telegram_api()
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>WARP Bot Dashboard</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
                .container { max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                h1 { color: #333; }
                .status { padding: 10px; margin: 10px 0; border-radius: 4px; }
                .online { background-color: #d4edda; color: #155724; }
                .offline { background-color: #f8d7da; color: #721c24; }
                .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 20px 0; }
                .stat-card { background: white; border: 1px solid #ddd; border-radius: 4px; padding: 15px; text-align: center; }
                .stat-value { font-size: 24px; font-weight: bold; margin: 10px 0; }
                pre { background: #f8f9fa; padding: 15px; border-radius: 4px; overflow-x: auto; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>WARP Bot Dashboard</h1>
                
                <div class="status {{ 'online' if api_status_ok else 'offline' }}">
                    Статус Telegram API: {{ api_status_message }}
                </div>
                
                <div class="stats">
                    <div class="stat-card">
                        <div>Активные пользователи</div>
                        <div class="stat-value">{{ active_users }}</div>
                    </div>
                    <div class="stat-card">
                        <div>Забаненные пользователи</div>
                        <div class="stat-value">{{ banned_users }}</div>
                    </div>
                    <div class="stat-card">
                        <div>Активные конфиги</div>
                        <div class="stat-value">{{ active_configs }}</div>
                    </div>
                    <div class="stat-card">
                        <div>Всего конфигов</div>
                        <div class="stat-value">{{ total_configs }}</div>
                    </div>
                </div>
                
                <h2>Активность пользователей (24 часа)</h2>
                <pre>{{ ascii_chart_day }}</pre>
                
                <div style="margin-top: 20px;">
                    <a href="/activity/day" style="margin-right: 10px;">24 часа</a>
                    <a href="/activity/week" style="margin-right: 10px;">Неделя</a>
                    <a href="/activity/month">Месяц</a>
                </div>
            </div>
        </body>
        </html>
    ''',
    active_users=active_users,
    banned_users=banned_users,
    active_configs=active_configs,
    total_configs=total_configs,
    ascii_chart_day=ascii_chart_day,
    api_status_ok=api_status_ok,
    api_status_message=api_status_message)

# Flask: График активности
@app.route('/activity/<range_type>')
async def activity_route(range_type):
    if range_type not in ["day", "week", "month"]:
        return "Недопустимый диапазон", 400
    
    ascii_chart = generate_ascii_chart(range_type)
    api_status_ok, api_status_message = await check_telegram_api()
    
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>WARP Bot Activity</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
                .container { max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                h1 { color: #333; }
                pre { background: #f8f9fa; padding: 15px; border-radius: 4px; overflow-x: auto; }
                a { color: #007bff; text-decoration: none; }
                a:hover { text-decoration: underline; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Активность пользователей ({{ range_type }})</h1>
                <pre>{{ ascii_chart }}</pre>
                <div style="margin-top: 20px;">
                    <a href="/activity/day" style="margin-right: 10px;">24 часа</a>
                    <a href="/activity/week" style="margin-right: 10px;">Неделя</a>
                    <a href="/activity/month" style="margin-right: 10px;">Месяц</a>
                    <a href="/">На главную</a>
                </div>
            </div>
        </body>
        </html>
    ''',
    range_type=range_type,
    ascii_chart=ascii_chart,
    api_status_ok=api_status_ok,
    api_status_message=api_status_message)

# Запуск бота
async def run_bot():
    global application
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("getconfig", get_config))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    
    application.add_handler(CallbackQueryHandler(button_handler))
    
    application.add_error_handler(error_handler)
    
    # Запуск бота
    await application.initialize()
    await application.start()
    
    # Удаляем вебхук и запускаем polling
    await application.bot.delete_webhook(drop_pending_updates=True)
    await application.updater.start_polling()
    
    logger.info("Бот запущен в режиме polling")

# Запуск Flask
def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# Главная функция
def main():
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=lambda: asyncio.run(run_bot()))
    bot_thread.daemon = True
    bot_thread.start()
    
    # Запускаем Flask в основном потоке
    run_flask()

if __name__ == "__main__":
    main()
