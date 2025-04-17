import logging
import sqlite3
import io
import json
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
import os
from dotenv import load_dotenv
import matplotlib.pyplot as plt

# Загрузка окружения
load_dotenv()
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Константы
BROADCAST_MESSAGE, ADD_CONFIG, EDIT_CONFIG = range(3)
CONFIG_TYPE, DNS_CHOICE = range(2)
STATS_DAYS = 30

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
    theme TEXT DEFAULT 'light')''')

cursor.execute('''CREATE TABLE IF NOT EXISTS configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    config_type TEXT,
    name TEXT,
    content TEXT,
    created_at TEXT,
    is_temporary INTEGER)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS user_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT,
    timestamp TEXT)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS dns_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dns_type TEXT,
    count INTEGER)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS config_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    template_data TEXT,
    created_at TEXT)''')

conn.commit()

# Инициализация начальных шаблонов конфигураций
def init_default_templates():
    default_templates = [
        {
            "name": "WireGuard",
            "template_data": {
                "PrivateKey": "7m8KfcDzbsd4MgqmzDyxnqguo6/RnzFHvDB90vEK8rI=",
                "PublicKey": "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=",
                "Address": "172.16.0.2, 2606:4700:110:8fda:bbc:18fb:580f:78a3",
                "Endpoint": "engage.cloudflareclient.com:2408",
                "DNS": {
                    'cloudflare': '1.1.1.1, 2606:4700:4700::1111, 1.0.0.1, 2606:4700:4700::1001',
                    'google': '8.8.8.8, 2001:4860:4860::8888',
                    'adguard': '94.140.14.14, 2a10:50c0::ad1:ff'
                },
                "extra_params": {}
            }
        },
        {
            "name": "AWG",
            "template_data": {
                "PrivateKey": "7m8KfcDzbsd4MgqmzDyxnqguo6/RnzFHvDB90vEK8rI=",
                "PublicKey": "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=",
                "Address": "172.16.0.2, 2606:4700:110:8fda:bbc:18fb:580f:78a3",
                "Endpoint": "engage.cloudflareclient.com:2408",
                "DNS": {
                    'cloudflare': '1.1.1.1, 2606:4700:4700::1111, 1.0.0.1, 2606:4700:4700::1001',
                    'google': '8.8.8.8, 2001:4860:4860::8888',
                    'adguard': '94.140.14.14, 2a10:50c0::ad1:ff'
                },
                "extra_params": {
                    "S1": 0,
                    "S2": 0,
                    "Jc": 4,
                    "Jmin": 40,
                    "Jmax": 70,
                    "H1": 1,
                    "H2": 2,
                    "H3": 3,
                    "H4": 4,
                    "MTU": 1280
                }
            }
        },
        {
            "name": "Veless Proxy",
            "template_data": {
                "PrivateKey": "aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789abcdefg=",
                "PublicKey": "zYxWvUtSrQpOnMlKjIhGfEdCbA9876543210zyxwvut=",
                "Address": "192.168.1.100",
                "Endpoint": "proxy.veless.com:8080",
                "DNS": {
                    'cloudflare': '1.1.1.1, 2606:4700:4700::1111',
                    'google': '8.8.8.8, 2001:4860:4860::8888',
                    'adguard': '94.140.14.14, 2a10:50c0::ad1:ff'
                },
                "extra_params": {
                    "ProxyType": "SOCKS5",
                    "Port": 8080
                }
            }
        }
    ]
    
    for template in default_templates:
        cursor.execute('''INSERT OR IGNORE INTO config_templates 
                       (name, template_data, created_at) 
                       VALUES (?, ?, ?)''',
                       (template['name'], json.dumps(template['template_data']), datetime.now().isoformat()))
    conn.commit()

init_default_templates()

# Функции БД
def register_user(user_id: int, username: str, full_name: str):
    cursor.execute('''INSERT OR IGNORE INTO users 
                   (user_id, username, full_name, created_at) 
                   VALUES (?, ?, ?, ?)''',
                   (user_id, username, full_name, datetime.now().isoformat()))
    conn.commit()

def save_config(user_id: int, content: str, config_type: str, name: str = 'auto', temp: bool = False):
    cursor.execute('''INSERT INTO configs 
                   (user_id, config_type, name, content, created_at, is_temporary) 
                   VALUES (?, ?, ?, ?, ?, ?)''',
                   (user_id, config_type, name, content, datetime.now().isoformat(), int(temp)))
    conn.commit()

def get_configs(user_id: int):
    cursor.execute('''SELECT id, config_type, name, content, created_at 
                   FROM configs WHERE user_id = ? 
                   ORDER BY created_at DESC''', (user_id,))
    return cursor.fetchall()

def delete_config(config_id: int):
    cursor.execute('DELETE FROM configs WHERE id = ?', (config_id,))
    conn.commit()

def log_activity(user_id: int, action: str):
    cursor.execute('''INSERT INTO user_activity 
                   (user_id, action, timestamp) 
                   VALUES (?, ?, ?)''',
                   (user_id, action, datetime.now().isoformat()))
    conn.commit()

def update_dns_stats(dns_type: str):
    cursor.execute('SELECT count FROM dns_usage WHERE dns_type = ?', (dns_type,))
    result = cursor.fetchone()
    if result:
        cursor.execute('''UPDATE dns_usage SET count = count + 1 
                       WHERE dns_type = ?''', (dns_type,))
    else:
        cursor.execute('INSERT INTO dns_usage (dns_type, count) VALUES (?, 1)', (dns_type,))
    conn.commit()

def get_user(user_id: int):
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    return cursor.fetchone()

def get_config_templates():
    cursor.execute('SELECT name, template_data FROM config_templates')
    return [(row[0], json.loads(row[1])) for row in cursor.fetchall()]

def add_config_template(name: str, template_data: dict):
    cursor.execute('''INSERT INTO config_templates 
                   (name, template_data, created_at) 
                   VALUES (?, ?, ?)''',
                   (name, json.dumps(template_data), datetime.now().isoformat()))
    conn.commit()

def update_config_template(name: str, template_data: dict):
    cursor.execute('''UPDATE config_templates 
                   SET template_data = ?, created_at = ? 
                   WHERE name = ?''',
                   (json.dumps(template_data), datetime.now().isoformat(), name))
    conn.commit()

def get_config_template(name: str):
    cursor.execute('SELECT template_data FROM config_templates WHERE name = ?', (name,))
    result = cursor.fetchone()
    return json.loads(result[0]) if result else None

def check_veless_limit(user_id: int) -> bool:
    """Проверяет, может ли пользователь создать конфиг Veless Proxy (1 в день)."""
    one_day_ago = (datetime.now() - timedelta(days=1)).isoformat()
    cursor.execute('''SELECT created_at FROM configs 
                   WHERE user_id = ? AND config_type = ? AND created_at >= ?''',
                   (user_id, 'Veless Proxy', one_day_ago))
    result = cursor.fetchone()
    return result is None  # True, если лимит не превышен (нет конфигов за последние 24 часа)

# Генерация конфигов
def generate_config(config_type: str, dns: str) -> str:
    template = get_config_template(config_type)
    if not template:
        return ""
    
    config = []
    if config_type == "Veless Proxy":
        # Формат для Veless Proxy (пример: SOCKS5 прокси)
        config.append(f"ProxyType = {template['extra_params']['ProxyType']}")
        config.append(f"Address = {template['Address']}")
        config.append(f"Port = {template['extra_params']['Port']}")
        config.append(f"Endpoint = {template['Endpoint']}")
        config.append(f"DNS = {template['DNS'][dns]}")
        config.append(f"PrivateKey = {template['PrivateKey']}")
        config.append(f"PublicKey = {template['PublicKey']}")
    else:
        # Формат для WireGuard/AWG
        config.append("[Interface]")
        config.append(f"PrivateKey = {template['PrivateKey']}")
        
        if 'extra_params' in template and template['extra_params']:
            for param, value in template['extra_params'].items():
                config.append(f"{param} = {value}")
        
        config.append(f"Address = {template['Address']}")
        config.append(f"DNS = {template['DNS'][dns]}")
        
        config.append("\n[Peer]")
        config.append(f"PublicKey = {template['PublicKey']}")
        config.append("AllowedIPs = 0.0.0.0/0, ::/0")
        config.append(f"Endpoint = {template['Endpoint']}")
    
    return "\n".join(config)

# Клавиатуры
def main_kb():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🔄 Новый конфиг"), KeyboardButton("📁 Мои конфиги")],
            [KeyboardButton("⚙️ Настройки"), KeyboardButton("ℹ️ Помощь")]
        ],
        resize_keyboard=True
    )

def configs_kb(configs):
    keyboard = []
    for cfg in configs:
        keyboard.append([InlineKeyboardButton(
            f"{cfg[2]} ({cfg[1]}, {cfg[4][:10]})", 
            callback_data=f"cfg_{cfg[0]}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='back_main')])
    return InlineKeyboardMarkup(keyboard)

def settings_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌑 Тёмная", callback_data='theme_dark'),
         InlineKeyboardButton("🌕 Светлая", callback_data='theme_light')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back_main')]
    ])

def config_type_kb():
    templates = get_config_templates()
    keyboard = [
        [InlineKeyboardButton(name, callback_data=name)]
        for name, _ in templates
    ]
    return InlineKeyboardMarkup(keyboard)

def dns_choice_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Cloudflare", callback_data='cloudflare'),
         InlineKeyboardButton("Google", callback_data='google')],
        [InlineKeyboardButton("AdGuard", callback_data='adguard')]
    ])

# Обработчики
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.full_name)
    log_activity(user.id, "start")
    await update.message.reply_text(
        "🚀 Добро пожаловать в Warp Generator!",
        reply_markup=main_kb()
    )

async def new_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity(update.effective_user.id, "new_config_start")
    templates = get_config_templates()
    if not templates:
        await update.message.reply_text("⛔ Нет доступных типов конфигураций")
        return ConversationHandler.END
    await update.message.reply_text(
        "Выберите тип конфигурации:",
        reply_markup=config_type_kb()
    )
    return CONFIG_TYPE

async def handle_config_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    config_type = query.data
    context.user_data['config_type'] = config_type
    
    await query.edit_message_text(
        f"Выбран {config_type}\nВыберите DNS сервер:",
        reply_markup=dns_choice_kb()
    )
    return DNS_CHOICE

async def handle_dns_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dns_type = query.data
    config_type = context.user_data['config_type']
    user_id = query.from_user.id
    
    # Проверка лимита для Veless Proxy
    if config_type == "Veless Proxy" and not check_veless_limit(user_id):
        await query.edit_message_text("⛔ Ошибка: Вы уже создали конфиг Veless Proxy сегодня. Попробуйте снова завтра.")
        return ConversationHandler.END
    
    config_content = generate_config(config_type, dns_type)
    if not config_content:
        await query.edit_message_text("⛔ Ошибка: шаблон конфигурации не найден")
        return ConversationHandler.END
    
    filename = f"{config_type}_{dns_type}.conf"
    
    save_config(user_id, config_content, config_type)
    update_dns_stats(dns_type)
    log_activity(user_id, f"config_created_{config_type}_{dns_type}")
    
    await context.bot.send_document(
        chat_id=query.message.chat_id,
        document=config_content.encode('utf-8'),
        filename=filename,
        caption=f"Ваш {config_type} конфиг"
    )
    
    await query.edit_message_text("✅ Конфиг успешно создан!")
    return ConversationHandler.END

async def show_configs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    configs = get_configs(user_id)
    log_activity(user_id, "view_configs")
    
    if not configs:
        await update.message.reply_text("📭 Нет сохранённых конфигов")
        return
    
    await update.message.reply_text(
        "📂 Ваши конфиги:",
        reply_markup=configs_kb(configs)
    )

async def config_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith('cfg_'):
        config_id = data.split('_')[1]
        cursor.execute('SELECT content FROM configs WHERE id = ?', (config_id,))
        content = cursor.fetchone()[0]
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Скачать", callback_data=f"down_{config_id}"),
             InlineKeyboardButton("🗑 Удалить", callback_data=f"del_{config_id}")],
            [InlineKeyboardButton("🔙 Назад", callback_data='back_configs')]
        ])
        await query.edit_message_text(
            f"⚙️ Конфиг #{config_id}",
            reply_markup=keyboard
        )
    
    elif data.startswith('down_'):
        config_id = data.split('_')[1]
        cursor.execute('SELECT content, config_type FROM configs WHERE id = ?', (config_id,))
        content, config_type = cursor.fetchone()
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=content.encode('utf-8'),
            filename=f'warp_{config_type}_{config_id}.conf'
        )
    
    elif data.startswith('del_'):
        config_id = data.split('_')[1]
        delete_config(config_id)
        await query.edit_message_text(f"🗑 Конфиг #{config_id} удалён")

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚙️ Настройки оформления:",
        reply_markup=settings_kb()
    )

async def set_theme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    theme = query.data.split('_')[1]
    user_id = query.from_user.id
    cursor.execute('UPDATE users SET theme = ? WHERE user_id = ?', (theme, user_id))
    conn.commit()
    await query.edit_message_text(f"✅ Тема изменена на {theme}")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "ℹ️ Доступные команды:\n\n"
        "🔄 Новый конфиг - создать новый конфиг\n"
        "📁 Мои конфиги - управление конфигами\n"
        "⚙️ Настройки - выбор темы оформления\n"
        "ℹ️ Помощь - это сообщение\n\n"
        "Админ-команды:\n"
        "/broadcast - рассылка\n"
        "/stats - статистика\n"
        "/userinfo USER_ID - информация о пользователе\n"
        "/addconfig - добавить новый тип конфигурации\n"
        "/editconfig - редактировать тип конфигурации"
    )
    await update.message.reply_text(text)

# Админ-функции
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    await update.message.reply_text("✉️ Введите сообщение для рассылки:")
    return BROADCAST_MESSAGE

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    cursor.execute('SELECT user_id FROM users')
    users = [row[0] for row in cursor.fetchall()]
    
    success = 0
    for user_id in users:
        try:
            await context.bot.send_message(user_id, f"📢 Рассылка:\n\n{message}")
            success += 1
        except Exception as e:
            logger.error(f"Ошибка отправки {user_id}: {str(e)}")
    
    await update.message.reply_text(
        f"✅ Отправлено: {success}\n❌ Ошибок: {len(users)-success}",
        reply_markup=main_kb()
    )
    return ConversationHandler.END

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    # График активности
    cursor.execute('''SELECT DATE(timestamp), COUNT(*) 
                   FROM user_activity 
                   WHERE timestamp >= DATE('now', '-30 days') 
                   GROUP BY DATE(timestamp)''')
    data = cursor.fetchall()
    
    dates = [row[0] for row in data]
    counts = [row[1] for row in data]
    
    plt.figure(figsize=(12, 6))
    plt.plot(dates, counts, marker='o')
    plt.title('Активность за 30 дней')
    plt.xticks(rotation=45)
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    
    # Статистика
    cursor.execute('SELECT COUNT(*) FROM users')
    total = cursor.fetchone()[0]
    cursor.execute('SELECT dns_type, SUM(count) FROM dns_usage GROUP BY dns_type')
    dns_stats = cursor.fetchall()
    
    # Статистика по типам конфигов
    cursor.execute('SELECT config_type, COUNT(*) FROM configs GROUP BY config_type')
    config_stats = cursor.fetchall()
    
    text = f"👥 Пользователей: {total}\n🔧 Конфигов: {sum(counts)}\n\n"
    text += "📊 Типы конфигов:\n" + "\n".join([f"{c[0]}: {c[1]}" for c in config_stats]) + "\n\n"
    text += "📊 DNS-серверы:\n" + "\n".join([f"{d[0]}: {d[1]}" for d in dns_stats])
    
    await update.message.reply_photo(
        photo=buf,
        caption=text
    )
    buf.close()

async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    try:
        user_id = int(context.args[0])
        user = get_user(user_id)
        if not user:
            await update.message.reply_text("❌ Пользователь не найден")
            return
        
        cursor.execute('''SELECT COUNT(*) FROM configs 
                       WHERE user_id = ?''', (user_id,))
        configs = cursor.fetchone()[0]
        
        cursor.execute('''SELECT action, COUNT(*) FROM user_activity 
                       WHERE user_id = ? GROUP BY action''', (user_id,))
        activity = cursor.fetchall()
        
        text = (
            f"🆔 ID: {user[0]}\n"
            f"👤 Имя: {user[3]}\n"
            f"📅 Регистрация: {user[4][:10]}\n"
            f"📂 Конфигов: {configs}\n"
            f"📈 Активность:\n"
        ) + "\n".join([f"{a[0]}: {a[1]}" for a in activity])
        
        await update.message.reply_text(text)
    except:
        await update.message.reply_text("Используйте: /userinfo USER_ID")

async def add_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    await update.message.reply_text(
        "Введите данные для нового типа конфигурации в формате JSON:\n"
        "{\n"
        '  "name": "ConfigName",\n'
        '  "template_data": {\n'
        '    "PrivateKey": "key",\n'
        '    "PublicKey": "key",\n'
        '    "Address": "ip",\n'
        '    "Endpoint": "endpoint",\n'
        '    "DNS": {\n'
        '      "cloudflare": "dns",\n'
        '      "google": "dns",\n'
        '      "adguard": "dns"\n'
        '    },\n'
        '    "extra_params": {}\n'
        '  }\n'
        "}"
    )
    return ADD_CONFIG

async def process_add_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return ConversationHandler.END
    
    try:
        config_data = json.loads(update.message.text)
        name = config_data['name']
        template_data = config_data['template_data']
        
        # Валидация
        required_fields = ['PrivateKey', 'PublicKey', 'Address', 'Endpoint', 'DNS']
        for field in required_fields:
            if field not in template_data:
                await update.message.reply_text(f"⛔ Ошибка: отсутствует поле {field}")
                return ConversationHandler.END
        if not isinstance(template_data['DNS'], dict) or not all(k in template_data['DNS'] for k in ['cloudflare', 'google', 'adguard']):
            await update.message.reply_text("⛔ Ошибка: неверный формат DNS")
            return ConversationHandler.END
        
        add_config_template(name, template_data)
        await update.message.reply_text(f"✅ Тип конфигурации '{name}' успешно добавлен!", reply_markup=main_kb())
    except json.JSONDecodeError:
        await update.message.reply_text("⛔ Ошибка: неверный формат JSON")
    except Exception as e:
        await update.message.reply_text(f"⛔ Ошибка: {str(e)}")
    
    return ConversationHandler.END

async def edit_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    templates = get_config_templates()
    if not templates:
        await update.message.reply_text("⛔ Нет доступных типов конфигураций")
        return
    
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"edit_{name}")]
        for name, _ in templates
    ]
    await update.message.reply_text(
        "Выберите тип конфигурации для редактирования:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def process_edit_config_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ Доступ запрещён!")
        return ConversationHandler.END
    
    config_type = query.data.split('_')[1]
    context.user_data['edit_config_type'] = config_type
    
    template = get_config_template(config_type)
    await query.edit_message_text(
        f"Текущие данные для '{config_type}':\n"
        f"{json.dumps(template, indent=2)}\n\n"
        "Введите новые данные в формате JSON:"
    )
    return EDIT_CONFIG

async def process_edit_config_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return ConversationHandler.END
    
    try:
        config_data = json.loads(update.message.text)
        name = context.user_data['edit_config_type']
        
        # Валидация
        required_fields = ['PrivateKey', 'PublicKey', 'Address', 'Endpoint', 'DNS']
        for field in required_fields:
            if field not in config_data:
                await update.message.reply_text(f"⛔ Ошибка: отсутствует поле {field}")
                return ConversationHandler.END
        if not isinstance(config_data['DNS'], dict) or not all(k in config_data['DNS'] for k in ['cloudflare', 'google', 'adguard']):
            await update.message.reply_text("⛔ Ошибка: неверный формат DNS")
            return ConversationHandler.END
        
        update_config_template(name, config_data)
        await update.message.reply_text(f"✅ Тип конфигурации '{name}' успешно обновлен!", reply_markup=main_kb())
    except json.JSONDecodeError:
        await update.message.reply_text("⛔ Ошибка: неверный формат JSON")
    except Exception as e:
        await update.message.reply_text(f"⛔ Ошибка: {str(e)}")
    
    return ConversationHandler.END

# Запуск
def main():
    app = Application.builder().token(TOKEN).build()
    
    # Основные команды
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex(r"🔄 Новый конфиг"), new_config)
        ],
        states={
            CONFIG_TYPE: [CallbackQueryHandler(handle_config_type)],
            DNS_CHOICE: [CallbackQueryHandler(handle_dns_choice, pattern=r"^(cloudflare|google|adguard)$")]
        },
        fallbacks=[]
    )
    
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.Regex(r"📁 Мои конфиги"), show_configs))
    app.add_handler(MessageHandler(filters.Regex(r"⚙️ Настройки"), settings))
    app.add_handler(MessageHandler(filters.Regex(r"ℹ️ Помощь"), help_cmd))
    
    # Колбэки
    app.add_handler(CallbackQueryHandler(config_action, pattern=r"^(cfg|down|del)_"))
    app.add_handler(CallbackQueryHandler(set_theme, pattern=r"^theme_"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: u.message.reply_text("🏠 Главное меню", reply_markup=main_kb()), 
        pattern=r"^back_"
    ))
    
    # Админка
    broadcast_handler = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast)],
        states={BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_broadcast)]},
        fallbacks=[]
    )
    app.add_handler(broadcast_handler)
    
    add_config_handler = ConversationHandler(
        entry_points=[CommandHandler("addconfig", add_config)],
        states={ADD_CONFIG: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_config)]},
        fallbacks=[]
    )
    app.add_handler(add_config_handler)
    
    edit_config_handler = ConversationHandler(
        entry_points=[CommandHandler("editconfig", edit_config)],
        states={
            EDIT_CONFIG: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_edit_config_data)],
            CONFIG_TYPE: [CallbackQueryHandler(process_edit_config_type, pattern=r"^edit_")]
        },
        fallbacks=[]
    )
    app.add_handler(edit_config_handler)
    
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("userinfo", user_info))
    
    app.run_polling()
    conn.close()

if __name__ == "__main__":
    main()
