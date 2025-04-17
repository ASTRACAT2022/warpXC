import logging
import sqlite3
import io
import json
import uuid
import csv
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
ADMIN_ID_RAW = os.getenv("ADMIN_ID")

if not TOKEN or not ADMIN_ID_RAW:
    raise ValueError("❌ TOKEN и ADMIN_ID должны быть указаны в .env файле")
try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except (TypeError, ValueError):
    raise ValueError("❌ ADMIN_ID должен быть числом")

# Константы
BROADCAST_MESSAGE, ADD_CONFIG, EDIT_CONFIG, SETTINGS, NOTIFY, ALL_USERS = range(6)
CONFIG_TYPE, DNS_CHOICE = range(2)
USERS_PER_PAGE = 10
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
    created_at TEXT,
    enabled INTEGER DEFAULT 1)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS banned_users (
    user_id INTEGER PRIMARY KEY,
    banned_at TEXT)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS site_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    site_name TEXT,
    created_at TEXT)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER,
    action TEXT,
    details TEXT,
    timestamp TEXT)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS bot_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    settings_key TEXT UNIQUE,
    settings_value TEXT)''')

conn.commit()

# Инициализация настроек бота
def init_default_settings():
    default_settings = {
        "welcome_message": "🚀 Добро пожаловать в Warp Generator!\n🆔 Ваш ID: {user_id}\n🔗 Реферальный код: {referral_code}",
        "veless_daily_limit": 1,
        "global_config_limit": 5,
        "config_cleanup_days": 30,
        "available_languages": json.dumps(["ru", "en"])
    }
    for key, value in default_settings.items():
        cursor.execute('''INSERT OR IGNORE INTO bot_settings 
                       (settings_key, settings_value) 
                       VALUES (?, ?)''', (key, json.dumps(value)))
    conn.commit()

init_default_settings()

# Получение настроек
def get_setting(key: str):
    cursor.execute('SELECT settings_value FROM bot_settings WHERE settings_key = ?', (key,))
    result = cursor.fetchone()
    return json.loads(result[0]) if result else None

# Обновление настроек
def update_setting(key: str, value):
    cursor.execute('''INSERT OR REPLACE INTO bot_settings 
                   (settings_key, settings_value) 
                   VALUES (?, ?)''', (key, json.dumps(value)))
    conn.commit()

# Проверка блокировки пользователя
def is_banned(user_id: int) -> bool:
    cursor.execute('SELECT user_id FROM banned_users WHERE user_id = ?', (user_id,))
    return cursor.fetchone() is not None

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
                    'cloudflare': '1.1.1.1, 2606:470的气氛0:4700::1111, 1.0.0.1, 2606:4700:4700::1001',
                    'google': '8.8.8.8, 2001:4860:4860::8888',
                    'adguard': '94.140.14.14, 2a10:50c0::ad1:ff'
                },
                "extra_params": {}
            },
            "enabled": 1
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
            },
            "enabled": 1
        },
        {
            "name": "AstraWarpBot",
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
            },
            "enabled": 1
        }
    ]
    
    for template in default_templates:
        cursor.execute('''INSERT OR IGNORE INTO config_templates 
                       (name, template_data, created_at, enabled) 
                       VALUES (?, ?, ?, ?)''',
                       (template['name'], json.dumps(template['template_data']), datetime.now().isoformat(), template['enabled']))
    conn.commit()
    cursor.execute('SELECT COUNT(*) FROM config_templates')
    count = cursor.fetchone()[0]
    logger.info(f"✅ Initialized {count} config templates")

init_default_templates()

# Функции БД
def register_user(user_id: int, username: str, full_name: str):
    referral_code = str(uuid.uuid4())[:8]
    cursor.execute('''INSERT OR IGNORE INTO users 
                   (user_id, username, full_name, created_at, referral_code) 
                   VALUES (?, ?, ?, ?, ?)''',
                   (user_id, username, full_name, datetime.now().isoformat(), referral_code))
    conn.commit()

def save_config(user_id: int, content: str, config_type: str, name: str = 'auto', temp: bool = False):
    cursor.execute('''INSERT INTO configs 
                   (user_id, config_type, name, content, created_at, is_temporary) 
                   VALUES (?, ?, ?, ?, ?, ?)''',
                   (user_id, config_type, name, content, datetime.now().isoformat(), int(temp)))
    conn.commit()

def save_site_request(user_id: int, site_name: str):
    cursor.execute('''INSERT INTO site_requests 
                   (user_id, site_name, created_at) 
                   VALUES (?, ?, ?)''',
                   (user_id, site_name, datetime.now().isoformat()))
    conn.commit()

def get_configs(user_id: int):
    cursor.execute('''SELECT id, config_type, name, content, created_at 
                   FROM configs WHERE user_id = ? 
                   ORDER BY created_at DESC''', (user_id,))
    return cursor.fetchall()

def get_site_requests(user_id: int):
    cursor.execute('''SELECT id, site_name, created_at 
                   FROM site_requests WHERE user_id = ? 
                   ORDER BY created_at DESC''', (user_id,))
    return cursor.fetchall()

def delete_config(config_id: int):
    cursor.execute('DELETE FROM configs WHERE id = ?', (config_id,))
    conn.commit()

def delete_site_request(request_id: int):
    cursor.execute('DELETE FROM site_requests WHERE id = ?', (request_id,))
    conn.commit()

def log_activity(user_id: int, action: str):
    cursor.execute('''INSERT INTO user_activity 
                   (user_id, action, timestamp) 
                   VALUES (?, ?, ?)''',
                   (user_id, action, datetime.now().isoformat()))
    conn.commit()

def log_admin_action(admin_id: int, action: str, details: str):
    cursor.execute('''INSERT INTO admin_logs 
                   (admin_id, action, details, timestamp) 
                   VALUES (?, ?, ?, ?)''',
                   (admin_id, action, details, datetime.now().isoformat()))
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
    cursor.execute('SELECT name, template_data, enabled FROM config_templates WHERE enabled = 1')
    templates = [(row[0], json.loads(row[1])) for row in cursor.fetchall()]
    logger.info(f"📋 Retrieved {len(templates)} config templates")
    return templates

def add_config_template(name: str, template_data: dict, enabled: bool = True):
    cursor.execute('''INSERT INTO config_templates 
                   (name, template_data, created_at, enabled) 
                   VALUES (?, ?, ?, ?)''',
                   (name, json.dumps(template_data), datetime.now().isoformat(), int(enabled)))
    conn.commit()

def update_config_template(name: str, template_data: dict, enabled: bool = True):
    cursor.execute('''UPDATE config_templates 
                   SET template_data = ?, created_at = ?, enabled = ? 
                   WHERE name = ?''',
                   (json.dumps(template_data), datetime.now().isoformat(), int(enabled), name))
    conn.commit()

def get_config_template(name: str):
    cursor.execute('SELECT template_data FROM config_templates WHERE name = ?', (name,))
    result = cursor.fetchone()
    return json.loads(result[0]) if result else None

def check_veless_limit(user_id: int) -> bool:
    limit = get_setting("veless_daily_limit") or 1
    one_day_ago = (datetime.now() - timedelta(days=1)).isoformat()
    cursor.execute('''SELECT COUNT(*) FROM site_requests 
                   WHERE user_id = ? AND site_name = ? AND created_at >= ?''',
                   (user_id, 'Xray VPN Veless', one_day_ago))
    count = cursor.fetchone()[0]
    return count < limit

def check_global_config_limit(user_id: int) -> bool:
    limit = get_setting("global_config_limit") or 5
    one_day_ago = (datetime.now() - timedelta(days=1)).isoformat()
    cursor.execute('''SELECT COUNT(*) FROM configs 
                   WHERE user_id = ? AND created_at >= ?''',
                   (user_id, one_day_ago))
    count = cursor.fetchone()[0]
    return count < limit

def ban_user(user_id: int):
    cursor.execute('''INSERT OR IGNORE INTO banned_users 
                   (user_id, banned_at) 
                   VALUES (?, ?)''',
                   (user_id, datetime.now().isoformat()))
    conn.commit()

def unban_user(user_id: int):
    cursor.execute('DELETE FROM banned_users WHERE user_id = ?', (user_id,))
    conn.commit()

def cleanup_old_configs():
    days = get_setting("config_cleanup_days") or 30
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    cursor.execute('DELETE FROM configs WHERE created_at < ?', (cutoff,))
    conn.commit()

def add_referral(user_id: int, referrer_code: str):
    cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (referrer_code,))
    referrer = cursor.fetchone()
    if referrer and referrer[0] != user_id:
        cursor.execute('UPDATE users SET referrer_id = ? WHERE user_id = ?', (referrer[0], user_id))
        conn.commit()
        return referrer[0]
    return None

def get_users_paginated(page: int = 0, filter_type: str = 'all', sort_by: str = 'created_at_desc', search_query: str = None):
    offset = page * USERS_PER_PAGE
    query = '''SELECT user_id, username, full_name, created_at 
               FROM users'''
    params = []
    
    # Фильтрация
    if filter_type == 'active':
        query += ''' WHERE user_id NOT IN (SELECT user_id FROM banned_users)'''
    elif filter_type == 'banned':
        query += ''' WHERE user_id IN (SELECT user_id FROM banned_users)'''
    
    # Поиск
    if search_query:
        if query.find('WHERE') == -1:
            query += ' WHERE '
        else:
            query += ' AND '
        query += '''(user_id LIKE ? OR username LIKE ? OR full_name LIKE ?)'''
        search_pattern = f'%{search_query}%'
        params.extend([search_pattern, search_pattern, search_pattern])
    
    # Сортировка
    if sort_by == 'created_at_asc':
        query += ' ORDER BY created_at ASC'
    elif sort_by == 'user_id':
        query += ' ORDER BY user_id ASC'
    else:  # created_at_desc
        query += ' ORDER BY created_at DESC'
    
    # Пагинация
    query += ' LIMIT ? OFFSET ?'
    params.extend([USERS_PER_PAGE, offset])
    
    cursor.execute(query, params)
    users = cursor.fetchall()
    
    # Подсчет общего количества
    count_query = '''SELECT COUNT(*) FROM users'''
    count_params = []
    if filter_type == 'active':
        count_query += ''' WHERE user_id NOT IN (SELECT user_id FROM banned_users)'''
    elif filter_type == 'banned':
        count_query += ''' WHERE user_id IN (SELECT user_id FROM banned_users)'''
    if search_query:
        if count_query.find('WHERE') == -1:
            count_query += ' WHERE '
        else:
            count_query += ' AND '
        count_query += '''(user_id LIKE ? OR username LIKE ? OR full_name LIKE ?)'''
        count_params.extend([search_pattern, search_pattern, search_pattern])
    
    cursor.execute(count_query, count_params)
    total_users = cursor.fetchone()[0]
    
    logger.info(f"📊 Retrieved {len(users)} users for page {page}, filter: {filter_type}, sort: {sort_by}")
    return users, total_users

def export_users_to_csv():
    cursor.execute('''SELECT user_id, username, full_name, created_at, 
                     CASE WHEN user_id IN (SELECT user_id FROM banned_users) THEN 'Banned' ELSE 'Active' END as status
                     FROM users''')
    users = cursor.fetchall()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Username', 'Full Name', 'Created At', 'Status'])
    for user in users:
        writer.writerow(user)
    
    output.seek(0)
    logger.info("📤 Generated CSV export for users")
    return output

# Генерация конфигов
def generate_config(config_type: str, dns: str) -> str:
    logger.info(f"⚙️ Generating config for type: {config_type}, DNS: {dns}")
    template = get_config_template(config_type)
    if not template:
        logger.error(f"❌ Template not found for config_type: {config_type}")
        return ""
    
    if 'DNS' not in template or dns not in template['DNS']:
        logger.error(f"❌ Invalid DNS configuration for {config_type}: {dns}")
        return ""
    
    try:
        config = []
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
        
        config_str = "\n".join(config)
        logger.info(f"✅ Config generated successfully for {config_type}")
        return config_str
    except Exception as e:
        logger.error(f"❌ Error generating config for {config_type}: {str(e)}")
        return ""

# Локализация
def get_text(key: str, language: str) -> str:
    texts = {
        "ru": {
            "welcome": "🚀 Добро пожаловать в Warp Generator!\n🆔 Ваш ID: {user_id}\n🔗 Реферальный код: {referral_code}",
            "banned": "🚫 Вы заблокированы и не можете использовать бота.",
            "config_limit": "⛔ Вы превысили дневной лимит создания конфигураций ({limit}). Попробуйте завтра!",
            "veless_limit": "⛔ Вы уже запрашивали Xray VPN Veless сегодня. Попробуйте завтра!",
            "veless_link": "🔗 Для получения Xray VPN Veless перейдите на сайт:",
            "config_created": "✅ Конфигурация успешно создана и отправлена!",
            "no_configs": "📭 У вас пока нет сохранённых конфигураций или запросов.",
            "no_users": "📭 Нет зарегистрированных пользователей.",
            "users_list": "📋 Список пользователей (стр. {page} из {total_pages}):\n\n{users}",
            "user_actions": "👤 Пользователь {user_id} ({full_name})",
            "search_users": "🔍 Введите ID или имя для поиска:",
            "new_config": "🆕 Создать конфигурацию",
            "my_configs": "📂 Мои конфигурации",
            "settings": "⚙️ Настройки",
            "help": (
                "ℹ️ Доступные команды:\n\n"
                "🆕 Создать конфигурацию - сгенерировать новый VPN-конфиг\n"
                "📂 Мои конфигурации - просмотр и управление вашими конфигами\n"
                "⚙️ Настройки - выбор темы и языка интерфейса\n"
                "ℹ️ Помощь - это сообщение\n"
                "🔗 /referral CODE - активировать реферальный код\n\n"
                "Админ-команды:\n"
                "📢 /broadcast - разослать сообщение всем\n"
                "📊 /stats - статистика использования\n"
                "👤 /userinfo USER_ID - информация о пользователе\n"
                "🆕 /addconfig - добавить новый тип конфигурации\n"
                "✏️ /editconfig - редактировать тип конфигурации\n"
                "📋 /listusers - список всех пользователей\n"
                "👥 /allusers - расширенный список пользователей\n"
                "🚫 /ban USER_ID - заблокировать пользователя\n"
                "✅ /unban USER_ID - разблокировать пользователя\n"
                "⚙️ /settings - настройки бота\n"
                "📩 /notify USER_ID MESSAGE - отправить уведомление"
            )
        },
        "en": {
            "welcome": "🚀 Welcome to Warp Generator!\n🆔 Your ID: {user_id}\n🔗 Referral code: {referral_code}",
            "banned": "🚫 You are banned and cannot use the bot.",
            "config_limit": "⛔ You have exceeded the daily config creation limit ({limit}). Try again tomorrow!",
            "veless_limit": "⛔ You have already requested Xray VPN Veless today. Try again tomorrow!",
            "veless_link": "🔗 To get Xray VPN Veless, visit the website:",
            "config_created": "✅ Configuration successfully created and sent!",
            "no_configs": "📭 You don't have any saved configs or requests yet.",
            "no_users": "📭 No registered users.",
            "users_list": "📋 Users list (page {page} of {total_pages}):\n\n{users}",
            "user_actions": "👤 User {user_id} ({full_name})",
            "search_users": "🔍 Enter ID or name to search:",
            "new_config": "🆕 Create Config",
            "my_configs": "📂 My Configs",
            "settings": "⚙️ Settings",
            "help": (
                "ℹ️ Available commands:\n\n"
                "🆕 Create Config - generate a new VPN config\n"
                "📂 My Configs - view and manage your configs\n"
                "⚙️ Settings - choose theme and language\n"
                "ℹ️ Help - this message\n"
                "🔗 /referral CODE - activate referral code\n\n"
                "Admin commands:\n"
                "📢 /broadcast - send message to all users\n"
                "📊 /stats - usage statistics\n"
                "👤 /userinfo USER_ID - user information\n"
                "🆕 /addconfig - add new config type\n"
                "✏️ /editconfig - edit config type\n"
                "📋 /listusers - list all users\n"
                "👥 /allusers - advanced users list\n"
                "🚫 /ban USER_ID - ban user\n"
                "✅ /unban USER_ID - unban user\n"
                "⚙️ /settings - bot settings\n"
                "📩 /notify USER_ID MESSAGE - send notification"
            )
        }
    }
    return texts.get(language, texts["ru"]).get(key, key).format(
        user_id="{user_id}", referral_code="{referral_code}", limit="{limit}",
        page="{page}", total_pages="{total_pages}", users="{users}", full_name="{full_name}"
    )

# Клавиатуры
def main_kb(language: str = 'ru'):
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(get_text("new_config", language)), KeyboardButton(get_text("my_configs", language))],
            [KeyboardButton(get_text("settings", language)), KeyboardButton("ℹ️ Помощь")]
        ],
        resize_keyboard=True
    )

def configs_kb(configs, requests, language: str = 'ru'):
    keyboard = []
    for cfg in configs:
        keyboard.append([InlineKeyboardButton(
            f"⚙️ {cfg[2]} ({cfg[1]}, {cfg[4][:10]})", 
            callback_data=f"cfg_{cfg[0]}"
        )])
    for req in requests:
        keyboard.append([InlineKeyboardButton(
            f"🌐 Xray VPN Veless ({req[2][:10]})", 
            callback_data=f"req_{req[0]}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 Назад в меню", callback_data='back_main')])
    return InlineKeyboardMarkup(keyboard)

def settings_kb(language: str = 'ru'):
    available_languages = get_setting("available_languages") or ["ru", "en"]
    lang_buttons = [
        InlineKeyboardButton(f"🌐 {lang.upper()}", callback_data=f"lang_{lang}")
        for lang in available_languages
    ]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌑 Тёмная тема", callback_data='theme_dark'),
         InlineKeyboardButton("🌕 Светлая тема", callback_data='theme_light')],
        lang_buttons,
        [InlineKeyboardButton("🔙 Назад в меню", callback_data='back_main')]
    ])

def config_type_kb(language: str = 'ru'):
    templates = get_config_templates()
    keyboard = [
        [InlineKeyboardButton(f"⚙️ {name}", callback_data=name)]
        for name, _ in templates
    ]
    keyboard.append([InlineKeyboardButton("🌐 Xray VPN Veless", callback_data='Xray VPN Veless')])
    return InlineKeyboardMarkup(keyboard)

def dns_choice_kb(language: str = 'ru'):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("☁️ Cloudflare DNS", callback_data='cloudflare'),
         InlineKeyboardButton("🌍 Google DNS", callback_data='google')],
        [InlineKeyboardButton("🛡️ AdGuard DNS", callback_data='adguard')]
    ])

def admin_settings_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить приветствие", callback_data='set_welcome'),
         InlineKeyboardButton("🔢 Лимит Veless", callback_data='set_veless_limit')],
        [InlineKeyboardButton("🔢 Лимит конфигов", callback_data='set_global_limit'),
         InlineKeyboardButton("🗑 Очистка старых конфигов", callback_data='set_cleanup_days')],
        [InlineKeyboardButton("🔙 Назад в меню", callback_data='back_main')]
    ])

def users_list_kb(page: int, total_users: int, filter_type: str, sort_by: str, language: str = 'ru'):
    total_pages = (total_users + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    keyboard = []
    
    # Фильтры
    keyboard.append([
        InlineKeyboardButton("👥 Все" if filter_type != 'all' else "✅ Все", callback_data=f"filter_all_{sort_by}_{page}"),
        InlineKeyboardButton("✅ Активные" if filter_type != 'active' else "✅ Активные", callback_data=f"filter_active_{sort_by}_{page}"),
        InlineKeyboardButton("🚫 Заблокированные" if filter_type != 'banned' else "✅ Заблокированные", callback_data=f"filter_banned_{sort_by}_{page}")
    ])
    
    # Сортировка
    keyboard.append([
        InlineKeyboardButton("📅 По дате ↓" if sort_by != 'created_at_desc' else "✅ По дате ↓", callback_data=f"sort_created_at_desc_{filter_type}_{page}"),
        InlineKeyboardButton("📅 По дате ↑" if sort_by != 'created_at_asc' else "✅ По дате ↑", callback_data=f"sort_created_at_asc_{filter_type}_{page}"),
        InlineKeyboardButton("🆔 По ID" if sort_by != 'user_id' else "✅ По ID", callback_data=f"sort_user_id_{filter_type}_{page}")
    ])
    
    # Пагинация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"page_{page-1}_{filter_type}_{sort_by}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f"page_{page+1}_{filter_type}_{sort_by}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Дополнительные действия
    keyboard.append([
        InlineKeyboardButton("🔍 Поиск", callback_data=f"search_{filter_type}_{sort_by}_{page}"),
        InlineKeyboardButton("📤 Экспорт в CSV", callback_data=f"export_{filter_type}_{sort_by}_{page}")
    ])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад в меню", callback_data='back_main')])
    return InlineKeyboardMarkup(keyboard)

def user_actions_kb(user_id: int, is_banned: bool, language: str = 'ru'):
    keyboard = [
        [
            InlineKeyboardButton("🚫 Заблокировать" if not is_banned else "✅ Разблокировать", 
                               callback_data=f"{'ban' if not is_banned else 'unban'}_{user_id}"),
            InlineKeyboardButton("📩 Отправить уведомление", callback_data=f"notify_{user_id}")
        ],
        [InlineKeyboardButton("🔙 Назад к списку", callback_data='back_users')]
    ]
    return InlineKeyboardMarkup(keyboard)

# Обработчики
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        language = get_user(user.id)[5] if get_user(user.id) else 'ru'
        await update.message.reply_text(get_text("banned", language))
        return
    
    register_user(user.id, user.username, user.full_name)
    user_data = get_user(user.id)
    language = user_data[5] or 'ru'
    referral_code = user_data[6]
    
    if context.args and context.args[0].startswith(':'):
        referrer_code = context.args[0][1:]
        referrer_id = add_referral(user.id, referrer_code)
        if referrer_id:
            log_activity(user.id, f"referral_activated_{referrer_id}")
            await context.bot.send_message(
                referrer_id,
                f"🎉 Новый пользователь ({user.full_name}) активировал ваш реферальный код! Вы получили +1 запрос Xray VPN Veless."
            )
    
    log_activity(user.id, "start")
    welcome_message = get_setting("welcome_message").format(user_id=user.id, referral_code=referral_code)
    await update.message.reply_text(welcome_message, reply_markup=main_kb(language))

async def new_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_banned(user_id):
        language = get_user(user_id)[5] or 'ru'
        await update.message.reply_text(get_text("banned", language))
        return ConversationHandler.END
    
    user = get_user(user_id)
    language = user[5] or 'ru'
    log_activity(user_id, "new_config_start")
    templates = get_config_templates()
    if not templates and not get_setting("veless_enabled", True):
        await update.message.reply_text("⛔ Нет доступных типов конфигураций. Свяжитесь с поддержкой.")
        return ConversationHandler.END
    await update.message.reply_text(
        "🆕 Выберите тип конфигурации:",
        reply_markup=config_type_kb(language)
    )
    return CONFIG_TYPE

async def handle_config_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if is_banned(user_id):
        language = get_user(user_id)[5] or 'ru'
        await query.edit_message_text(get_text("banned", language))
        return ConversationHandler.END
    
    user = get_user(user_id)
    language = user[5] or 'ru'
    await query.answer()
    config_type = query.data
    context.user_data['config_type'] = config_type
    
    if config_type == "Xray VPN Veless":
        if not check_veless_limit(user_id):
            await query.edit_message_text(get_text("veless_limit", language))
            return ConversationHandler.END
        
        save_site_request(user_id, config_type)
        log_activity(user_id, f"site_requested_{config_type}")
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Перейти на сайт", url="https://astracat2022.github.io/vpngen")]
        ])
        await query.edit_message_text(
            get_text("veless_link", language),
            reply_markup=keyboard
        )
        return ConversationHandler.END
    
    if not check_global_config_limit(user_id):
        limit = get_setting("global_config_limit") or 5
        await query.edit_message_text(get_text("config_limit", language).format(limit=limit))
        return ConversationHandler.END
    
    await query.edit_message_text(
        f"⚙️ Выбран тип: {config_type}\nВыберите DNS-сервер:",
        reply_markup=dns_choice_kb(language)
    )
    return DNS_CHOICE

async def handle_dns_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if is_banned(user_id):
        language = get_user(user_id)[5] or 'ru'
        await query.edit_message_text(get_text("banned", language))
        return ConversationHandler.END
    
    user = get_user(user_id)
    language = user[5] or 'ru'
    await query.answer()
    dns_type = query.data
    config_type = context.user_data.get('config_type')
    
    logger.info(f"🔍 Handling DNS choice: user={user_id}, config_type={config_type}, dns={dns_type}")
    
    if not config_type:
        logger.error(f"❌ No config_type in user_data for user {user_id}")
        await query.edit_message_text("⛔ Ошибка: тип конфигурации не выбран. Попробуйте снова.")
        return ConversationHandler.END
    
    config_content = generate_config(config_type, dns_type)
    if not config_content:
        logger.error(f"❌ Failed to generate config for user {user_id}, type {config_type}, dns {dns_type}")
        await query.edit_message_text("⛔ Ошибка: не удалось создать конфигурацию. Свяжитесь с поддержкой.")
        return ConversationHandler.END
    
    try:
        filename = "astrawarpbot.conf" if config_type == "AstraWarpBot" else f"{config_type}_{dns_type}.conf"
        
        save_config(user_id, config_content, config_type)
        update_dns_stats(dns_type)
        log_activity(user_id, f"config_created_{config_type}_{dns_type}")
        
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=io.BytesIO(config_content.encode('utf-8')),
            filename=filename,
            caption=f"⚙️ Ваш {config_type} конфиг готов!"
        )
        
        await query.edit_message_text(get_text("config_created", language))
        logger.info(f"✅ Config sent to user {user_id}: {filename}")
    except Exception as e:
        logger.error(f"❌ Error sending config to user {user_id}: {str(e)}")
        await query.edit_message_text(f"⛔ Ошибка при отправке конфигурации: {str(e)}")
    
    return ConversationHandler.END

async def show_configs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_banned(user_id):
        language = get_user(user_id)[5] or 'ru'
        await update.message.reply_text(get_text("banned", language))
        return
    
    user = get_user(user_id)
    language = user[5] or 'ru'
    configs = get_configs(user_id)
    requests = get_site_requests(user_id)
    log_activity(user_id, "view_configs")
    
    if not configs and not requests:
        await update.message.reply_text(get_text("no_configs", language))
        return
    
    await update.message.reply_text(
        "📂 Ваши конфигурации и запросы:",
        reply_markup=configs_kb(configs, requests, language)
    )

async def config_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if is_banned(user_id):
        language = get_user(user_id)[5] or 'ru'
        await query.edit_message_text(get_text("banned", language))
        return
    
    user = get_user(user_id)
    language = user[5] or 'ru'
    await query.answer()
    data = query.data
    
    if data.startswith('cfg_'):
        config_id = data.split('_')[1]
        cursor.execute('SELECT content, config_type FROM configs WHERE id = ?', (config_id,))
        content, config_type = cursor.fetchone()
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Скачать снова", callback_data=f"down_{config_id}"),
             InlineKeyboardButton("🗑 Удалить", callback_data=f"del_{config_id}")],
            [InlineKeyboardButton("🔙 Назад к списку", callback_data='back_configs')]
        ])
        await query.edit_message_text(
            f"⚙️ Конфигурация #{config_id} ({config_type})",
            reply_markup=keyboard
        )
    
    elif data.startswith('req_'):
        request_id = data.split('_')[1]
        cursor.execute('SELECT site_name, created_at FROM site_requests WHERE id = ?', (request_id,))
        site_name, created_at = cursor.fetchone()
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Перейти на сайт", url="https://astracat2022.github.io/vpngen")],
            [InlineKeyboardButton("🗑 Удалить запрос", callback_data=f"delreq_{request_id}")],
            [InlineKeyboardButton("🔙 Назад к списку", callback_data='back_configs')]
        ])
        await query.edit_message_text(
            f"🌐 Запрос #{request_id} ({site_name}, {created_at[:10]})",
            reply_markup=keyboard
        )
    
    elif data.startswith('down_'):
        config_id = data.split('_')[1]
        cursor.execute('SELECT content, config_type FROM configs WHERE id = ?', (config_id,))
        content, config_type = cursor.fetchone()
        filename = "astrawarpbot.conf" if config_type == "AstraWarpBot" else f"warp_{config_type}_{config_id}.conf"
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=io.BytesIO(content.encode('utf-8')),
            filename=filename
        )
    
    elif data.startswith('del_'):
        config_id = data.split('_')[1]
        delete_config(config_id)
        await query.edit_message_text(f"🗑 Конфигурация #{config_id} удалена")
    
    elif data.startswith('delreq_'):
        request_id = data.split('_')[1]
        delete_site_request(request_id)
        await query.edit_message_text(f"🗑 Запрос #{request_id} удалён")

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_banned(user_id):
        language = get_user(user_id)[5] or 'ru'
        await update.message.reply_text(get_text("banned", language))
        return
    
    user = get_user(user_id)
    language = user[5] or 'ru'
    await update.message.reply_text(
        "⚙️ Настройте тему и язык:",
        reply_markup=settings_kb(language)
    )

async def set_theme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if is_banned(user_id):
        language = get_user(user_id)[5] or 'ru'
        await query.edit_message_text(get_text("banned", language))
        return
    
    user = get_user(user_id)
    language = user[5] or 'ru'
    await query.answer()
    theme = query.data.split('_')[1]
    cursor.execute('UPDATE users SET theme = ? WHERE user_id = ?', (theme, user_id))
    conn.commit()
    await query.edit_message_text(f"✅ Тема изменена на {'тёмную' if theme == 'dark' else 'светлую'}")

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if is_banned(user_id):
        language = get_user(user_id)[5] or 'ru'
        await query.edit_message_text(get_text("banned", language))
        return
    
    await query.answer()
    language = query.data.split('_')[1]
    cursor.execute('UPDATE users SET language = ? WHERE user_id = ?', (language, user_id))
    conn.commit()
    await query.edit_message_text(f"✅ Язык изменён на {language.upper()}")

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_banned(user_id):
        language = get_user(user_id)[5] or 'ru'
        await update.message.reply_text(get_text("banned", language))
        return
    
    user = get_user(user_id)
    language = user[5] or 'ru'
    
    if not context.args:
        await update.message.reply_text(f"🔗 Ваш реферальный код: {user[6]}\nПоделитесь им с друзьями!")
        return
    
    referrer_code = context.args[0]
    referrer_id = add_referral(user_id, referrer_code)
    if referrer_id:
        log_activity(user_id, f"referral_activated_{referrer_id}")
        await update.message.reply_text("🎉 Реферальный код активирован! Вы получили +1 запрос Xray VPN Veless.")
        await context.bot.send_message(
            referrer_id,
            f"🎉 Новый пользователь активировал ваш реферальный код! Вы получили +1 запрос Xray VPN Veless."
        )
    else:
        await update.message.reply_text("⛔ Неверный или ваш собственный реферальный код.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_banned(user_id):
        language = get_user(user_id)[5] or 'ru'
        await update.message.reply_text(get_text("banned", language))
        return
    
    user = get_user(user_id)
    language = user[5] or 'ru'
    await update.message.reply_text(get_text("help", language))

# Админ-функции
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    await update.message.reply_text("📢 Введите сообщение для рассылки всем пользователям:")
    return BROADCAST_MESSAGE

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return ConversationHandler.END
    
    message = update.message.text
    cursor.execute('SELECT user_id, language FROM users')
    users = cursor.fetchall()
    
    success = 0
    for user_id, language in users:
        if is_banned(user_id):
            continue
        try:
            await context.bot.send_message(user_id, f"📢 Рассылка:\n\n{message}")
            success += 1
        except Exception as e:
            logger.error(f"❌ Ошибка отправки {user_id}: {str(e)}")
    
    log_admin_action(ADMIN_ID, "broadcast", f"Sent to {success} users")
    await update.message.reply_text(
        f"✅ Отправлено: {success}\n❌ Ошибок: {len(users)-success}",
        reply_markup=main_kb('ru')
    )
    return ConversationHandler.END

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    periods = [
        ("1 день", 1),
        ("7 дней", 7),
        ("30 дней", 30)
    ]
    
    text = "📊 Статистика использования:\n\n"
    for period_name, days in periods:
        cursor.execute('''SELECT COUNT(*) 
                       FROM user_activity 
                       WHERE timestamp >= DATE('now', ? || ' days')''', (f"-{days}",))
        activity_count = cursor.fetchone()[0]
        
        cursor.execute('''SELECT config_type, COUNT(*) 
                       FROM configs 
                       WHERE created_at >= DATE('now', ? || ' days') 
                       GROUP BY config_type''', (f"-{days}",))
        config_stats = cursor.fetchall()
        
        cursor.execute('''SELECT COUNT(*) 
                       FROM site_requests 
                       WHERE created_at >= DATE('now', ? || ' days') 
                       AND site_name = ?''', (f"-{days}", 'Xray VPN Veless'))
        veless_requests = cursor.fetchone()[0]
        
        cursor.execute('''SELECT dns_type, count 
                       FROM dns_usage''')
        dns_stats = cursor.fetchall()
        
        text += f"📅 За {period_name}:\n"
        text += f"👥 Активность: {activity_count}\n"
        text += f"⚙️ Конфигураций: {sum(c[1] for c in config_stats)}\n"
        text += "\n".join([f"  {c[0]}: {c[1]}" for c in config_stats]) + "\n"
        text += f"🌐 Xray VPN Veless: {veless_requests}\n"
        text += "📊 DNS-серверы:\n" + "\n".join([f"  {d[0]}: {d[1]}" for d in dns_stats]) + "\n\n"
        
        cursor.execute('''SELECT DATE(timestamp), COUNT(*) 
                       FROM user_activity 
                       WHERE timestamp >= DATE('now', ? || ' days') 
                       GROUP BY DATE(timestamp)''', (f"-{days}",))
        data = cursor.fetchall()
        
        dates = [row[0] for row in data]
        counts = [row[1] for row in data]
        
        plt.figure(figsize=(12, 6))
        plt.plot(dates, counts, marker='o')
        plt.title(f'Активность за {period_name}')
        plt.xticks(rotation=45)
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()
        
        await update.message.reply_photo(
            photo=buf,
            caption=text
        )
        buf.close()
        text = ""

async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    try:
        target_id = int(context.args[0])
        user = get_user(target_id)
        if not user:
            await update.message.reply_text("❌ Пользователь не найден")
            return
        
        cursor.execute('''SELECT COUNT(*) FROM configs 
                       WHERE user_id = ?''', (target_id,))
        configs = cursor.fetchone()[0]
        
        cursor.execute('''SELECT COUNT(*) FROM site_requests 
                       WHERE user_id = ? AND site_name = ?''', (target_id, 'Xray VPN Veless'))
        veless_requests = cursor.fetchone()[0]
        
        cursor.execute('''SELECT action, COUNT(*) FROM user_activity 
                       WHERE user_id = ? GROUP BY action''', (target_id,))
        activity = cursor.fetchall()
        
        is_banned_status = "🚫 Заблокирован" if is_banned(target_id) else "✅ Активен"
        
        text = (
            f"🆔 ID: {user[0]}\n"
            f"👤 Имя: {user[3]}\n"
            f"📅 Регистрация: {user[4][:10]}\n"
            f"🚫 Статус: {is_banned_status}\n"
            f"⚙️ Конфигураций: {configs}\n"
            f"🌐 Xray VPN Veless: {veless_requests}\n"
            f"📈 Активность:\n"
        ) + "\n".join([f"  {a[0]}: {a[1]}" for a in activity])
        
        await update.message.reply_text(text)
    except:
        await update.message.reply_text("ℹ️ Используйте: /userinfo USER_ID")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    cursor.execute('SELECT user_id, full_name, created_at FROM users ORDER BY created_at')
    users = cursor.fetchall()
    
    if not users:
        await update.message.reply_text(get_text("no_users", 'ru'))
        return
    
    text = "📋 Список пользователей:\n\n"
    for user in users:
        is_banned_status = "🚫" if is_banned(user[0]) else "✅"
        text += f"🆔 {user[0]} | 👤 {user[1]} | 📅 {user[2][:10]} | {is_banned_status}\n"
    
    await update.message.reply_text(text)

async def all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    context.user_data['all_users_filter'] = 'all'
    context.user_data['all_users_sort'] = 'created_at_desc'
    context.user_data['all_users_page'] = 0
    context.user_data['all_users_search'] = None
    
    if context.args and context.args[0] == 'search':
        await update.message.reply_text(get_text("search_users", 'ru'))
        return ALL_USERS
    
    users, total_users = get_users_paginated()
    if not users:
        await update.message.reply_text(get_text("no_users", 'ru'))
        return
    
    user_list = ""
    for user in users:
        user_id, username, full_name, created_at = user
        status = "🚫" if is_banned(user_id) else "✅"
        user_list += f"🆔 {user_id} | 👤 {full_name or username or 'N/A'} | 📅 {created_at[:10]} | {status}\n"
    
    total_pages = (total_users + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    await update.message.reply_text(
        get_text("users_list", 'ru').format(page=1, total_pages=total_pages, users=user_list),
        reply_markup=users_list_kb(0, total_users, 'all', 'created_at_desc')
    )
    log_admin_action(user_id, "view_all_users", "Viewed users list")
    return ALL_USERS

async def handle_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id != ADMIN_ID:
        await query.edit_message_text("⛔ Доступ запрещён!")
        return ConversationHandler.END
    
    await query.answer()
    data = query.data.split('_')
    action = data[0]
    
    filter_type = context.user_data.get('all_users_filter', 'all')
    sort_by = context.user_data.get('all_users_sort', 'created_at_desc')
    page = context.user_data.get('all_users_page', 0)
    search_query = context.user_data.get('all_users_search')
    
    if action in ['page', 'filter', 'sort']:
        if action == 'page':
            page = int(data[1])
            filter_type = data[2]
            sort_by = data[3]
        elif action == 'filter':
            filter_type = data[1]
            sort_by = data[2]
            page = int(data[3])
        elif action == 'sort':
            sort_by = data[1]
            filter_type = data[2]
            page = int(data[3])
        
        context.user_data['all_users_filter'] = filter_type
        context.user_data['all_users_sort'] = sort_by
        context.user_data['all_users_page'] = page
        
        users, total_users = get_users_paginated(page, filter_type, sort_by, search_query)
        if not users:
            await query.edit_message_text(get_text("no_users", 'ru'))
            return
        
        user_list = ""
        for user in users:
            user_id, username, full_name, created_at = user
            status = "🚫" if is_banned(user_id) else "✅"
            user_list += f"🆔 {user_id} | 👤 {full_name or username or 'N/A'} | 📅 {created_at[:10]} | {status}\n"
        
        total_pages = (total_users + USERS_PER_PAGE - 1) // USERS_PER_PAGE
        await query.edit_message_text(
            get_text("users_list", 'ru').format(page=page+1, total_pages=total_pages, users=user_list),
            reply_markup=users_list_kb(page, total_users, filter_type, sort_by)
        )
    
    elif action == 'search':
        context.user_data['all_users_filter'] = data[1]
        context.user_data['all_users_sort'] = data[2]
        context.user_data['all_users_page'] = int(data[3])
        await query.edit_message_text(get_text("search_users", 'ru'))
        return ALL_USERS
    
    elif action == 'export':
        filter_type = data[1]
        sort_by = data[2]
        page = int(data[3])
        csv_file = export_users_to_csv()
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=csv_file,
            filename="users.csv",
            caption="📤 Экспортированный список пользователей"
        )
        csv_file.close()
        log_admin_action(user_id, "export_users", f"Exported users list (filter: {filter_type}, sort: {sort_by})")
    
    elif action in ['ban', 'unban']:
        target_id = int(data[1])
        if target_id == ADMIN_ID:
            await query.edit_message_text("⛔ Нельзя заблокировать администратора!")
            return
        
        if action == 'ban':
            ban_user(target_id)
            action_text = "banned"
        else:
            unban_user(target_id)
            action_text = "unbanned"
        
        log_admin_action(user_id, action, f"User {target_id} {action_text}")
        user = get_user(target_id)
        await query.edit_message_text(
            get_text("user_actions", 'ru').format(user_id=target_id, full_name=user[3] or user[2] or 'N/A'),
            reply_markup=user_actions_kb(target_id, is_banned(target_id))
        )
    
    elif action == 'notify':
        target_id = int(data[1])
        context.user_data['notify_user_id'] = target_id
        await query.edit_message_text("📩 Введите сообщение для пользователя:")
        return NOTIFY
    
    elif action == 'user':
        target_id = int(data[1])
        user = get_user(target_id)
        await query.edit_message_text(
            get_text("user_actions", 'ru').format(user_id=target_id, full_name=user[3] or user[2] or 'N/A'),
            reply_markup=user_actions_kb(target_id, is_banned(target_id))
        )
    
    elif action == 'back_users':
        users, total_users = get_users_paginated(page, filter_type, sort_by, search_query)
        if not users:
            await query.edit_message_text(get_text("no_users", 'ru'))
            return
        
        user_list = ""
        for user in users:
            user_id, username, full_name, created_at = user
            status = "🚫" if is_banned(user_id) else "✅"
            user_list += f"🆔 {user_id} | 👤 {full_name or username or 'N/A'} | 📅 {created_at[:10]} | {status}\n"
        
        total_pages = (total_users + USERS_PER_PAGE - 1) // USERS_PER_PAGE
        await query.edit_message_text(
            get_text("users_list", 'ru').format(page=page+1, total_pages=total_pages, users=user_list),
            reply_markup=users_list_kb(page, total_users, filter_type, sort_by)
        )

async def process_search_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return ConversationHandler.END
    
    search_query = update.message.text
    context.user_data['all_users_search'] = search_query
    filter_type = context.user_data.get('all_users_filter', 'all')
    sort_by = context.user_data.get('all_users_sort', 'created_at_desc')
    page = 0
    context.user_data['all_users_page'] = page
    
    users, total_users = get_users_paginated(page, filter_type, sort_by, search_query)
    if not users:
        await update.message.reply_text(get_text("no_users", 'ru'))
        return ConversationHandler.END
    
    user_list = ""
    for user in users:
        user_id, username, full_name, created_at = user
        status = "🚫" if is_banned(user_id) else "✅"
        user_list += f"🆔 {user_id} | 👤 {full_name or username or 'N/A'} | 📅 {created_at[:10]} | {status}\n"
    
    total_pages = (total_users + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    await update.message.reply_text(
        get_text("users_list", 'ru').format(page=page+1, total_pages=total_pages, users=user_list),
        reply_markup=users_list_kb(page, total_users, filter_type, sort_by)
    )
    log_admin_action(user_id, "search_users", f"Searched users with query: {search_query}")
    return ALL_USERS

async def notify_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return ConversationHandler.END
    
    target_id = context.user_data.get('notify_user_id')
    if not target_id:
        await update.message.reply_text("⛔ Ошибка: пользователь не выбран")
        return ConversationHandler.END
    
    message = update.message.text
    try:
        await context.bot.send_message(target_id, f"📢 Уведомление от админа:\n{message}")
        log_admin_action(user_id, "notify", f"Sent to {target_id}: {message}")
        await update.message.reply_text(f"✅ Уведомление отправлено пользователю {target_id}", reply_markup=main_kb('ru'))
    except Exception as e:
        await update.message.reply_text(f"⛔ Ошибка: {str(e)}")
    
    return ConversationHandler.END

async def ban_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    try:
        target_id = int(context.args[0])
        if target_id == ADMIN_ID:
            await update.message.reply_text("⛔ Нельзя заблокировать администратора!")
            return
        
        ban_user(target_id)
        log_admin_action(user_id, "ban", f"Banned user {target_id}")
        await update.message.reply_text(f"🚫 Пользователь {target_id} заблокирован")
    except:
        await update.message.reply_text("ℹ️ Используйте: /ban USER_ID")

async def unban_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    try:
        target_id = int(context.args[0])
        unban_user(target_id)
        log_admin_action(user_id, "unban", f"Unbanned user {target_id}")
        await update.message.reply_text(f"✅ Пользователь {target_id} разблокирован")
    except:
        await update.message.reply_text("ℹ️ Используйте: /unban USER_ID")

async def admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    await update.message.reply_text(
        "⚙️ Настройки бота:",
        reply_markup=admin_settings_kb()
    )
    return SETTINGS

async def handle_admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id != ADMIN_ID:
        await query.edit_message_text("⛔ Доступ запрещён!")
        return ConversationHandler.END
    
    await query.answer()
    action = query.data
    
    if action == 'set_welcome':
        await query.edit_message_text(
            "✏️ Введите новое приветственное сообщение (используйте {user_id}, {referral_code}):"
        )
        context.user_data['setting_key'] = 'welcome_message'
    
    elif action == 'set_veless_limit':
        await query.edit_message_text("🔢 Введите новый дневной лимит запросов Xray VPN Veless:")
        context.user_data['setting_key'] = 'veless_daily_limit'
    
    elif action == 'set_global_limit':
        await query.edit_message_text("🔢 Введите новый дневной лимит конфигураций:")
        context.user_data['setting_key'] = 'global_config_limit'
    
    elif action == 'set_cleanup_days':
        await query.edit_message_text("🗑 Введите количество дней для хранения конфигураций:")
        context.user_data['setting_key'] = 'config_cleanup_days'
    
    return SETTINGS

async def process_admin_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return ConversationHandler.END
    
    setting_key = context.user_data.get('setting_key')
    value = update.message.text
    
    try:
        if setting_key in ['veless_daily_limit', 'global_config_limit', 'config_cleanup_days']:
            value = int(value)
            if value < 0:
                raise ValueError("Значение должно быть неотрицательным")
        update_setting(setting_key, value)
        log_admin_action(user_id, "update_setting", f"Updated {setting_key} to {value}")
        await update.message.reply_text(
            f"✅ Настройка {setting_key} обновлена: {value}",
            reply_markup=main_kb('ru')
        )
    except Exception as e:
        await update.message.reply_text(f"⛔ Ошибка: {str(e)}")
    
    return ConversationHandler.END

async def add_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    await update.message.reply_text(
        "🆕 Введите название нового типа конфигурации:"
    )
    return ADD_CONFIG

async def process_add_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return ConversationHandler.END
    
    config_name = update.message.text
    context.user_data['new_config_name'] = config_name
    await update.message.reply_text(
        "⚙️ Введите JSON с данными шаблона конфигурации:"
    )
    return ADD_CONFIG

async def finalize_add_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return ConversationHandler.END
    
    config_name = context.user_data.get('new_config_name')
    try:
        template_data = json.loads(update.message.text)
        add_config_template(config_name, template_data)
        log_admin_action(user_id, "add_config", f"Added config {config_name}")
        await update.message.reply_text(
            f"✅ Тип конфигурации {config_name} добавлен",
            reply_markup=main_kb('ru')
        )
    except Exception as e:
        await update.message.reply_text(f"⛔ Ошибка: {str(e)}")
    
    return ConversationHandler.END

async def edit_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return
    
    templates = get_config_templates()
    keyboard = [
        [InlineKeyboardButton(f"⚙️ {name}", callback_data=f"edit_{name}")]
        for name, _ in templates
    ]
    keyboard.append([InlineKeyboardButton("🔙 Назад в меню", callback_data='back_main')])
    await update.message.reply_text(
        "✏️ Выберите тип конфигурации для редактирования:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return EDIT_CONFIG

async def handle_edit_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id != ADMIN_ID:
        await query.edit_message_text("⛔ Доступ запрещён!")
        return ConversationHandler.END
    
    await query.answer()
    config_name = query.data.split('_')[1]
    context.user_data['edit_config_name'] = config_name
    await query.edit_message_text(
        f"⚙️ Введите новый JSON для шаблона {config_name}:"
    )
    return EDIT_CONFIG

async def finalize_edit_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён!")
        return ConversationHandler.END
    
    config_name = context.user_data.get('edit_config_name')
    try:
        template_data = json.loads(update.message.text)
        update_config_template(config_name, template_data)
        log_admin_action(user_id, "edit_config", f"Edited config {config_name}")
        await update.message.reply_text(
            f"✅ Тип конфигурации {config_name} обновлён",
            reply_markup=main_kb('ru')
        )
    except Exception as e:
        await update.message.reply_text(f"⛔ Ошибка: {str(e)}")
    
    return ConversationHandler.END

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user = get_user(user_id)
    language = user[5] if user else 'ru'
    
    await query.answer()
    await query.edit_message_text(
        "🔙 Вернулись в главное меню",
        reply_markup=main_kb(language)
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    language = user[5] if user else 'ru'
    
    await update.message.reply_text(
        "🚫 Действие отменено",
        reply_markup=main_kb(language)
    )
    return ConversationHandler.END

def main():
    application = Application.builder().token(TOKEN).build()
    
    # ConversationHandler для создания конфигурации
    config_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(🆕 Создать конфигурацию|🆕 Create Config)$"), new_config)],
        states={
            CONFIG_TYPE: [CallbackQueryHandler(handle_config_type)],
            DNS_CHOICE: [CallbackQueryHandler(handle_dns_choice)]
        },
        fallbacks=[CallbackQueryHandler(back_to_main, pattern='^back_main$'),
                   CommandHandler("cancel", cancel)]
    )
    
    # ConversationHandler для рассылки
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast)],
        states={
            BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_broadcast)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    # ConversationHandler для добавления конфигурации
    add_config_conv = ConversationHandler(
        entry_points=[CommandHandler("addconfig", add_config)],
        states={
            ADD_CONFIG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_config),
                MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_add_config)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    # ConversationHandler для редактирования конфигурации
    edit_config_conv = ConversationHandler(
        entry_points=[CommandHandler("editconfig", edit_config)],
        states={
            EDIT_CONFIG: [
                CallbackQueryHandler(handle_edit_config, pattern='^edit_'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_edit_config)
            ]
        },
        fallbacks=[CallbackQueryHandler(back_to_main, pattern='^back_main$'),
                   CommandHandler("cancel", cancel)]
    )
    
    # ConversationHandler для настроек
    settings_conv = ConversationHandler(
        entry_points=[CommandHandler("settings", admin_settings)],
        states={
            SETTINGS: [
                CallbackQueryHandler(handle_admin_settings),
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_admin_settings)
            ]
        },
        fallbacks=[CallbackQueryHandler(back_to_main, pattern='^back_main$'),
                   CommandHandler("cancel", cancel)]
    )
    
    # ConversationHandler для списка пользователей
    users_conv = ConversationHandler(
        entry_points=[CommandHandler("allusers", all_users)],
        states={
            ALL_USERS: [
                CallbackQueryHandler(handle_users_list),
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_search_users)
            ],
            NOTIFY: [MessageHandler(filters.TEXT & ~filters.COMMAND, notify_user)]
        },
        fallbacks=[CallbackQueryHandler(back_to_main, pattern='^back_main$'),
                   CommandHandler("cancel", cancel)]
    )
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("referral", referral))
    application.add_handler(MessageHandler(filters.Regex("^(📂 Мои конфигурации|📂 My Configs)$"), show_configs))
    application.add_handler(CallbackQueryHandler(config_action, pattern='^(cfg_|req_|down_|del_|delreq_)'))
    application.add_handler(MessageHandler(filters.Regex("^(⚙️ Настройки|⚙️ Settings)$"), settings))
    application.add_handler(CallbackQueryHandler(set_theme, pattern='^theme_'))
    application.add_handler(CallbackQueryHandler(set_language, pattern='^lang_'))
    application.add_handler(CallbackQueryHandler(back_to_main, pattern='^back_main$'))
    application.add_handler(config_conv)
    application.add_handler(broadcast_conv)
    application.add_handler(add_config_conv)
    application.add_handler(edit_config_conv)
    application.add_handler(settings_conv)
    application.add_handler(users_conv)
    
    # Админ-команды
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("userinfo", user_info))
    application.add_handler(CommandHandler("listusers", list_users))
    application.add_handler(CommandHandler("ban", ban_user_cmd))
    application.add_handler(CommandHandler("unban", unban_user_cmd))
    
    # Запуск бота
    logger.info("🚀 Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("🛑 Bot stopped")

if __name__ == '__main__':
    main()
