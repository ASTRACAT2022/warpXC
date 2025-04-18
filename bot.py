import logging
import sqlite3
import io
import json
import uuid
import csv
import os
import subprocess
from datetime import datetime, timedelta
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
import matplotlib.pyplot as plt
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv

# Загрузка окружения
load_dotenv()
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Константы
BROADCAST_MESSAGE, ADD_CONFIG, EDIT_CONFIG, SETTINGS, NOTIFY, ALL_USERS = range(6)
CONFIG_TYPE, DNS_CHOICE = range(2)
USERS_PER_PAGE = 10

# Настройка логов
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# База данных
conn = sqlite3.connect('warp_bot.db', check_same_thread=False)
cursor = conn.cursor()

# Инициализация БД
cursor.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    created_at TEXT,
    theme TEXT DEFAULT 'light',
    language TEXT DEFAULT 'ru',
    referral_code TEXT,
    referrer_id INTEGER)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    config_type TEXT,
    name TEXT,
    content TEXT,
    created_at TEXT,
    is_temporary INTEGER)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT,
    size INTEGER)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS bot_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    settings_key TEXT UNIQUE,
    settings_value TEXT)''')

# ... (остальные таблицы из предыдущего кода)

# Инициализация настроек
def init_default_settings():
    default_settings = {
        "welcome_message": "🚀 Добро пожаловать в Warp Generator!",
        "veless_daily_limit": 1,
        "global_config_limit": 5,
        "config_cleanup_days": 30,
        "last_cleanup": None
    }
    for key, value in default_settings.items():
        cursor.execute('''INSERT OR IGNORE INTO bot_settings 
                       (settings_key, settings_value) 
                       VALUES (?, ?)''', (key, json.dumps(value)))
    conn.commit()

init_default_settings()

# Генерация ключей WireGuard
def generate_private_key():
    return x25519.X25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    ).hex()

def derive_public_key(private_key: str):
    private_key_bytes = bytes.fromhex(private_key)
    private_key = x25519.X25519PrivateKey.from_private_bytes(private_key_bytes)
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    ).hex()

# Новые функции БД
def create_backup_record(size: int):
    cursor.execute('''INSERT INTO backups 
                   (created_at, size) 
                   VALUES (?, ?)''',
                   (datetime.now().isoformat(), size))
    conn.commit()

def get_referral_stats():
    cursor.execute('''SELECT referrer_id, COUNT(*) as count 
                   FROM users 
                   WHERE referrer_id IS NOT NULL 
                   GROUP BY referrer_id 
                   ORDER BY count DESC''')
    return cursor.fetchall()

# Обработчики новых команд
async def referral_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    stats = get_referral_stats()
    if not stats:
        await update.message.reply_text("📊 Нет реферальных данных")
        return
    
    text = "📊 Топ рефереров:\n\n"
    for idx, (referrer_id, count) in enumerate(stats[:10], 1):
        user = get_user(referrer_id)
        username = user[2] if user else "Неизвестный"
        text += f"{idx}. {username} (ID: {referrer_id}): {count} приглашений\n"
    
    await update.message.reply_text(text)

async def backup_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    try:
        with open('warp_bot.db', 'rb') as db_file:
            content = db_file.read()
            backup_size = len(content)
            create_backup_record(backup_size)
            
            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=io.BytesIO(content),
                filename=f"warp_backup_{datetime.now().strftime('%Y%m%d')}.db"
            )
            log_admin_action(ADMIN_ID, "backup", f"Created backup, size: {backup_size} bytes")
    except Exception as e:
        await update.message.reply_text(f"⛔ Ошибка создания бэкапа: {str(e)}")

async def server_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    # Статистика системы
    try:
        disk = subprocess.check_output(["df", "-h"]).decode()
        memory = subprocess.check_output(["free", "-m"]).decode()
    except:
        disk = memory = "N/A"

    # Статистика бота
    cursor.execute('SELECT COUNT(*) FROM users')
    users_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM configs')
    configs_count = cursor.fetchone()[0]
    
    text = (
        "🖥 Статус сервера:\n\n"
        f"👥 Пользователей: {users_count}\n"
        f"⚙️ Конфигураций: {configs_count}\n"
        f"📅 Последняя очистка: {get_setting('last_cleanup') or 'Никогда'}\n\n"
        "💽 Диск:\n" + "\n".join(disk.split("\n")[:3]) + "\n\n"
        "🧠 Память:\n" + "\n".join(memory.split("\n")[:2])
    )
    
    await update.message.reply_text(text[:4000])

async def rotate_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    templates = get_config_templates()
    for name, template in templates:
        new_private = generate_private_key()
        new_public = derive_public_key(new_private)
        
        template['PrivateKey'] = new_private
        template['PublicKey'] = new_public
        update_config_template(name, template)
    
    log_admin_action(ADMIN_ID, "key_rotation", "Rotated all keys")
    await update.message.reply_text("✅ Ключи успешно обновлены во всех шаблонах")

async def activity_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    cursor.execute('''SELECT DATE(timestamp), COUNT(*) 
                   FROM user_activity 
                   GROUP BY DATE(timestamp) 
                   ORDER BY DATE(timestamp) DESC 
                   LIMIT 30''')
    data = cursor.fetchall()
    
    dates = [row[0] for row in data][::-1]
    counts = [row[1] for row in data][::-1]
    
    plt.figure(figsize=(12, 6))
    plt.bar(dates, counts)
    plt.title('Активность пользователей')
    plt.xticks(rotation=45)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    
    await update.message.reply_photo(
        photo=buf,
        caption="📈 График активности за 30 дней"
    )
    buf.close()

# Обновленный обработчик main
def main():
    application = Application.builder().token(TOKEN).build()

    # ... (существующие обработчики из предыдущего кода)

    # Добавляем новые обработчики
    application.add_handler(CommandHandler("referral_stats", referral_stats))
    application.add_handler(CommandHandler("backup", backup_db))
    application.add_handler(CommandHandler("server_status", server_status))
    application.add_handler(CommandHandler("rotate_keys", rotate_keys))
    application.add_handler(CommandHandler("activity_graph", activity_graph))

    # Планировщик задач
    async def daily_tasks(context: ContextTypes.DEFAULT_TYPE):
        cleanup_old_configs()
        update_setting("last_cleanup", datetime.now().isoformat())
        logger.info("✅ Ежедневное обслуживание выполнено")

    application.job_queue.run_daily(
        daily_tasks,
        time=datetime.time(3, 0, 0, tzinfo=datetime.timezone.utc)
    )

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
