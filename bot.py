import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from datetime import datetime, timedelta
import uuid
import os
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import numpy as np

# Загрузка переменных из .env
load_dotenv()

# Проверка переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")

if not BOT_TOKEN:
    raise ValueError("Ошибка: Переменная окружения BOT_TOKEN не задана.")
if not ADMIN_TELEGRAM_ID:
    raise ValueError("Ошибка: Переменная окружения ADMIN_TELEGRAM_ID не задана.")

try:
    ADMIN_TELEGRAM_ID = int(ADMIN_TELEGRAM_ID)
except ValueError:
    raise ValueError("Ошибка: ADMIN_TELEGRAM_ID должен быть числом.")

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect("warp_bot.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        last_config_time TEXT,
        is_banned INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS configs (
        config_id TEXT PRIMARY KEY,
        telegram_id INTEGER,
        created_at TEXT,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
    )''')
    conn.commit()
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

# Создание клавиатуры для пользователей
def get_user_keyboard():
    keyboard = [
        [InlineKeyboardButton("Получить конфиг", callback_data="get_config")],
        [InlineKeyboardButton("Справка", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect("warp_bot.db")
    c = conn.cursor()
    
    # Регистрация пользователя
    c.execute(
        "INSERT OR REPLACE INTO users (telegram_id, username, first_name, last_name, last_config_time, is_banned) VALUES (?, ?, ?, ?, ?, ?)",
        (user.id, user.username, user.first_name, user.last_name, None, 0)
    )
    conn.commit()
    conn.close()
    
    welcome_message = (
        "Добро пожаловать! Используйте кнопки ниже для взаимодействия с ботом.\n"
        "Админ команды: /stats, /users, /ban, /unban, /broadcast"
    )
    await update.message.reply_text(welcome_message, reply_markup=get_user_keyboard())

# Обработчик команды /getconfig и кнопки
async def get_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if hasattr(update, 'callback_query'):
        user = update.callback_query.from_user
        message = update.callback_query.message
    else:
        user = update.effective_user
        message = update.message

    conn = sqlite3.connect("warp_bot.db")
    c = conn.cursor()
    
    # Проверка на бан
    c.execute("SELECT is_banned FROM users WHERE telegram_id = ?", (user.id,))
    result = c.fetchone()
    if result and result[0] == 1:
        await message.reply_text("Вы забанены и не можете получать конфигурации.")
        conn.close()
        return
    
    # Проверка времени последнего запроса (лимит 1 конфиг в 24 часа)
    c.execute("SELECT last_config_time FROM users WHERE telegram_id = ?", (user.id,))
    last_config_time = c.fetchone()[0]
    if last_config_time:
        last_time = datetime.fromisoformat(last_config_time)
        if datetime.now() - last_time < timedelta(hours=24):
            await message.reply_text(
                "Вы можете запрашивать новую конфигурацию раз в 24 часа. Попробуйте позже."
            )
            conn.close()
            return
    
    # Генерация и сохранение конфигурации
    config = generate_warp_config()
    config_id = str(uuid.uuid4())
    c.execute(
        "INSERT INTO configs (config_id, telegram_id, created_at, is_active) VALUES (?, ?, ?, ?)",
        (config_id, user.id, datetime.now().isoformat(), 1)
    )
    c.execute(
        "UPDATE users SET last_config_time = ? WHERE telegram_id = ?",
        (datetime.now().isoformat(), user.id)
    )
    conn.commit()
    conn.close()
    
    # Отправка конфигурации
    with open(f"config_{user.id}.conf", "w") as f:
        f.write(config)
    with open(f"config_{user.id}.conf", "rb") as f:
        await message.reply_document(document=f, filename="warp.conf")
    os.remove(f"config_{user.id}.conf")

# Обработчик кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "get_config":
        await get_config(query, context)
    elif query.data == "help":
        help_message = (
            "📖 Справка по боту:\n"
            "- Нажмите 'Получить конфиг' или используйте /getconfig для получения WARP конфигурации.\n"
            "- Конфигурации выдаются раз в 24 часа.\n"
            "- Для админов доступны команды: /stats, /users, /ban, /unban, /broadcast."
        )
        await query.message.reply_text(help_message, reply_markup=get_user_keyboard())

# Обработчик команды /stats (для админа)
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return
    
    conn = sqlite3.connect("warp_bot.db")
    c = conn.cursor()
    
    # Статистика
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
    banned_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM configs WHERE is_active = 1")
    active_configs = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM configs")
    total_configs = c.fetchone()[0]
    
    stats_message = (
        f"📊 Статистика бота:\n"
        f"Всего пользователей: {total_users}\n"
        f"Забаненных пользователей: {banned_users}\n"
        f"Активных конфигураций: {active_configs}\n"
        f"Всего выдано конфигураций: {total_configs}"
    )
    
    # График 1: Пользователи (всего и забаненные)
    plt.figure(figsize=(8, 6))
    labels = ['Всего пользователей', 'Забаненные']
    values = [total_users, banned_users]
    plt.bar(labels, values, color=['blue', 'red'])
    plt.title('Статистика пользователей')
    plt.ylabel('Количество')
    plt.grid(True, axis='y')
    plt.savefig('users_stats.png')
    plt.close()
    
    # График 2: Конфигурации (активные и всего)
    plt.figure(figsize=(8, 6))
    labels = ['Активные конфиги', 'Всего конфигов']
    values = [active_configs, total_configs]
    plt.bar(labels, values, color=['green', 'purple'])
    plt.title('Статистика конфигураций')
    plt.ylabel('Количество')
    plt.grid(True, axis='y')
    plt.savefig('configs_stats.png')
    plt.close()
    
    conn.close()
    
    # Отправка статистики и графиков
    await update.message.reply_text(stats_message)
    with open('users_stats.png', 'rb') as f:
        await update.message.reply_photo(photo=f, caption="Статистика пользователей")
    with open('configs_stats.png', 'rb') as f:
        await update.message.reply_photo(photo=f, caption="Статистика конфигураций")
    
    # Удаление временных файлов
    os.remove('users_stats.png')
    os.remove('configs_stats.png')

# Обработчик команды /users (для админа)
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
    
    await update.message.reply_text(users_message)

# Обработчик команды /ban (для админа)
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return
    
    if not context.args:
        await update.message.reply_text("Укажите Telegram ID пользователя: /ban <telegram_id>")
        return
    
    try:
        target_id = int(context.args[0])
        conn = sqlite3.connect("warp_bot.db")
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned = 1 WHERE telegram_id = ?", (target_id,))
        conn.commit()
        conn.close()
        await context.bot.send_message(chat_id=target_id, text="Вы были забанены администратором и больше не можете получать конфигурации.")
        await update.message.reply_text(f"Пользователь {target_id} забанен.")
    except ValueError:
        await update.message.reply_text("Неверный формат Telegram ID.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка при попытке забанить пользователя: {e}")

# Обработчик команды /unban (для админа)
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return
    
    if not context.args:
        await update.message.reply_text("Укажите Telegram ID пользователя: /unban <telegram_id>")
        return
    
    try:
        target_id = int(context.args[0])
        conn = sqlite3.connect("warp_bot.db")
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned = 0 WHERE telegram_id = ?", (target_id,))
        conn.commit()
        conn.close()
        await context.bot.send_message(chat_id=target_id, text="Вы были разбанены администратором и теперь можете получать конфигурации.")
        await update.message.reply_text(f"Пользователь {target_id} разбанен.")
    except ValueError:
        await update.message.reply_text("Неверный формат Telegram ID.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка при попытке разбанить пользователя: {e}")

# Обработчик команды /broadcast (для админа)
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return
    
    if not context.args:
        await update.message.reply_text("Укажите сообщение для рассылки: /broadcast <сообщение>")
        return
    
    message = " ".join(context.args)
    conn = sqlite3.connect("warp_bot.db")
    c = conn.cursor()
    c.execute("SELECT telegram_id FROM users WHERE is_banned = 0")
    users = c.fetchall()
    conn.close()
    
    for user in users:
        try:
            await context.bot.send_message(chat_id=user[0], text=message)
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения пользователю {user[0]}: {e}")
    
    await update.message.reply_text("Рассылка завершена.")

# Обработчик ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("getconfig", get_config))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("users", users))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Запуск бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
