import sqlite3
import logging
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

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = "7935425343:AAECbjFJvLHkeTvwHAKDG8uvmy-KiWcPtns"
ADMIN_TELEGRAM_ID = 650154766  # Ваш ID в Telegram
DB_FILE = "warp_bot.db"

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Таблица пользователей
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
        
        # Таблица конфигураций
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS configs (
            config_id TEXT PRIMARY KEY,
            telegram_id INTEGER,
            created_at DATETIME,
            is_active INTEGER DEFAULT 1,
            FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
        )
        ''')
        
        self.conn.commit()
    
    def add_user(self, user):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO users (telegram_id, username, first_name, last_name, first_seen) "
            "VALUES (?, ?, ?, ?, ?)",
            (user.id, user.username, user.first_name, user.last_name, datetime.now())
        )
        self.conn.commit()
    
    def is_banned(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT is_banned FROM users WHERE telegram_id = ?", (user_id,))
        result = cursor.fetchone()
        return result and result[0] == 1
    
    def can_get_config(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT last_config_time FROM users WHERE telegram_id = ?", (user_id,))
        result = cursor.fetchone()
        
        if not result or not result[0]:
            return True
            
        last_time = datetime.fromisoformat(result[0])
        return datetime.now() - last_time >= timedelta(hours=24)
    
    def add_config(self, user_id):
        cursor = self.conn.cursor()
        config_id = str(uuid.uuid4())
        
        cursor.execute(
            "INSERT INTO configs (config_id, telegram_id, created_at) VALUES (?, ?, ?)",
            (config_id, user_id, datetime.now())
        )
        
        cursor.execute(
            "UPDATE users SET last_config_time = ? WHERE telegram_id = ?",
            (datetime.now().isoformat(), user_id)
        )
        
        self.conn.commit()
        return config_id
    
    def get_stats(self):
        cursor = self.conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0")
        active_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
        banned_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM configs WHERE is_active = 1")
        active_configs = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM configs")
        total_configs = cursor.fetchone()[0]
        
        return active_users, banned_users, active_configs, total_configs
    
    def get_users_list(self, limit=50):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT telegram_id, username, first_name, is_banned FROM users ORDER BY first_seen DESC LIMIT ?",
            (limit,)
        )
        return cursor.fetchall()
    
    def ban_user(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("UPDATE users SET is_banned = 1 WHERE telegram_id = ?", (user_id,))
        self.conn.commit()
    
    def unban_user(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("UPDATE users SET is_banned = 0 WHERE telegram_id = ?", (user_id,))
        self.conn.commit()
    
    def get_active_users(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT telegram_id FROM users WHERE is_banned = 0")
        return [row[0] for row in cursor.fetchall()]

# Инициализация базы данных
db = Database()

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

def is_admin(user_id):
    return user_id == ADMIN_TELEGRAM_ID

def get_main_keyboard(user_id):
    keyboard = [
        [
            InlineKeyboardButton("Получить конфиг", callback_data="get_config"),
            InlineKeyboardButton("Справка", callback_data="help"),
        ],
        [
            InlineKeyboardButton("XrayVPN", url="https://astracat2022.github.io/vpngen/generator"),
        ]
    ]
    
    if is_admin(user_id):
        keyboard.append([
            InlineKeyboardButton("Статистика", callback_data="stats"),
            InlineKeyboardButton("Пользователи", callback_data="users"),
        ])
    
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Новый пользователь: {user.id}")
    
    db.add_user(user)
    
    await update.message.reply_text(
        f"Привет, {user.first_name or 'пользователь'}! 👋\n"
        "Я бот для генерации WARP конфигураций. Выберите действие:",
        reply_markup=get_main_keyboard(user.id)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    data = query.data
    
    if data == "get_config":
        await get_config(update, context)
    elif data == "help":
        await help_command(update, context)
    elif data == "stats" and is_admin(user.id):
        await stats_command(update, context)
    elif data == "users" and is_admin(user.id):
        await users_command(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    help_text = (
        "📚 Справка по боту:\n\n"
        "Этот бот генерирует конфигурации для WARP.\n\n"
        "Основные команды:\n"
        "/start - Начать работу с ботом\n"
        "/getconfig - Получить конфигурацию\n\n"
        "Конфигурацию можно запрашивать раз в 24 часа."
    )
    
    if is_admin(user.id):
        help_text += (
            "\n\nАдмин-команды:\n"
            "/stats - Статистика бота\n"
            "/users - Список пользователей\n"
            "/ban <id> - Забанить пользователя\n"
            "/unban <id> - Разбанить пользователя\n"
            "/broadcast <текст> - Сделать рассылку"
        )
    
    await query.edit_message_text(
        help_text,
        reply_markup=get_main_keyboard(user.id)
    )

async def get_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if db.is_banned(user.id):
        await update.message.reply_text("❌ Вы забанены и не можете получать конфигурации.")
        return
    
    if not db.can_get_config(user.id):
        await update.message.reply_text(
            "⏳ Вы можете запрашивать конфигурацию только раз в 24 часа. "
            "Попробуйте позже."
        )
        return
    
    config = generate_warp_config()
    db.add_config(user.id)
    
    # Сохраняем конфиг во временный файл
    config_file = f"warp_{user.id}.conf"
    with open(config_file, "w") as f:
        f.write(config)
    
    # Отправляем файл пользователю
    with open(config_file, "rb") as f:
        await context.bot.send_document(
            chat_id=user.id,
            document=f,
            filename="warp.conf",
            caption="Ваша WARP конфигурация"
        )
    
    # Удаляем временный файл
    import os
    os.remove(config_file)
    
    logger.info(f"Пользователь {user.id} получил конфигурацию")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда только для администратора.")
        return
    
    active_users, banned_users, active_configs, total_configs = db.get_stats()
    
    response = (
        "📊 Статистика бота:\n\n"
        f"👥 Пользователи: {active_users} активных, {banned_users} забаненных\n"
        f"📂 Конфигурации: {active_configs} активных, {total_configs} всего"
    )
    
    await update.message.reply_text(response)

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда только для администратора.")
        return
    
    users = db.get_users_list()
    
    if not users:
        await update.message.reply_text("Нет пользователей в базе данных.")
        return
    
    response = "👥 Последние 50 пользователей:\n\n"
    for user in users:
        status = "🚫" if user[3] else "✅"
        response += f"{status} ID: {user[0]}, Username: @{user[1]}, Имя: {user[2]}\n"
    
    await update.message.reply_text(response)

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда только для администратора.")
        return
    
    if not context.args:
        await update.message.reply_text("Использование: /ban <user_id>")
        return
    
    try:
        user_id = int(context.args[0])
        db.ban_user(user_id)
        
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

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда только для администратора.")
        return
    
    if not context.args:
        await update.message.reply_text("Использование: /unban <user_id>")
        return
    
    try:
        user_id = int(context.args[0])
        db.unban_user(user_id)
        
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

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Эта команда только для администратора.")
        return
    
    if not context.args:
        await update.message.reply_text("Использование: /broadcast <сообщение>")
        return
    
    message = " ".join(context.args)
    users = db.get_active_users()
    
    if not users:
        await update.message.reply_text("Нет активных пользователей для рассылки.")
        return
    
    success = 0
    failed = 0
    
    progress_msg = await update.message.reply_text(f"Начинаю рассылку для {len(users)} пользователей...")
    
    for user_id in users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📢 Сообщение от администратора:\n\n{message}"
            )
            success += 1
        except Exception as e:
            failed += 1
            logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
        
        # Обновляем статус каждые 10 отправок
        if (success + failed) % 10 == 0:
            await progress_msg.edit_text(
                f"Рассылка в процессе...\n"
                f"✅ Успешно: {success}\n"
                f"❌ Не удалось: {failed}"
            )
        
        # Небольшая задержка, чтобы не превысить лимиты Telegram
        await asyncio.sleep(0.1)
    
    await progress_msg.edit_text(
        f"Рассылка завершена:\n"
        f"✅ Успешно: {success}\n"
        f"❌ Не удалось: {failed}"
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)
    
    if update and update.callback_query:
        try:
            await update.callback_query.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")
        except:
            pass
    
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text("Произошла ошибка. Пожалуйста, попробуйте позже.")
        except:
            pass

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("getconfig", get_config))
    
    # Админ-команды
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    
    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()
