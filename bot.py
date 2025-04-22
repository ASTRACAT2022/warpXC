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
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
import threading
import asyncio

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
WEB_SECRET_KEY = "your-secret-key"  # Секретный ключ для Flask
ADMIN_USERNAME = "astracat"  # Имя пользователя для входа в веб-интерфейс
ADMIN_PASSWORD_HASH = generate_password_hash("astracat")  # Пароль

# Инициализация Flask и Telegram Application
app = Flask(__name__)
app.secret_key = WEB_SECRET_KEY
application = None  # Глобальная переменная для Telegram Application

# Класс базы данных
class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
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
    config = """[Interface]
PrivateKey = CS/UQwV5cCjhGdH/1FQbSkRLvYU8Ha1xeTkHVg5rizI=
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
PublicKey = bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = 162.159.192.227:894
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
            InlineKeyboardButton("XrayVPN", url="https://astracat2022.github.io/info"),
        ]
    ]
    
    if is_admin(user_id):
        keyboard.append([
            InlineKeyboardButton("Статистика", callback_data="stats"),
            InlineKeyboardButton("Пользователи", callback_data="users"),
        ])
    
    return InlineKeyboardMarkup(keyboard)

# Flask routes
@app.route('/')
async def index():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    active_users, banned_users, active_configs, total_configs = db.get_stats()
    stats_text = (
        "📊 Статистика бота:\n\n"
        f"👥 Пользователи: {active_users} активных, {banned_users} забаненных\n"
        f"📂 Конфигурации: {active_configs} активных, {total_configs} всего"
    )
    
    # Проверка связи с Telegram API
    try:
        await application.bot.get_me()
        api_status = {"connected": True, "message": "🟢 Подключено"}
    except Exception as e:
        api_status = {"connected": False, "message": f"🔴 Отключено: {str(e)}"}
    
    return render_template('index.html', stats_text=stats_text, api_status=api_status)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['logged_in'] = True
            flash('Успешный вход!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Неверное имя пользователя или пароль.', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('login'))

@app.route('/users')
def users():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    users = db.get_users_list()
    return render_template('users.html', users=users)

@app.route('/ban/<int:user_id>')
def ban_user(user_id):
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    db.ban_user(user_id)
    flash(f'Пользователь {user_id} забанен.', 'success')
    return redirect(url_for('users'))

@app.route('/unban/<int:user_id>')
def unban_user(user_id):
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    db.unban_user(user_id)
    flash(f'Пользователь {user_id} разбанен.', 'success')
    return redirect(url_for('users'))

@app.route('/broadcast', methods=['GET', 'POST'])
async def broadcast():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        message = request.form.get('message')
        if not message:
            flash('Сообщение не может быть пустым.', 'error')
            return redirect(url_for('broadcast'))
        
        users = db.get_active_users()
        if not users:
            flash('Нет активных пользователей для рассылки.', 'warning')
            return redirect(url_for('broadcast'))
        
        success = 0
        failed = 0
        
        for user_id in users:
            try:
                await application.bot.send_message(
                    chat_id=user_id,
                    text=f"📢 Сообщение от администратора:\n\n{message}"
                )
                success += 1
            except Exception as e:
                failed += 1
                logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
            
            # Небольшая задержка, чтобы не превысить лимиты Telegram
            await asyncio.sleep(0.1)
        
        flash(f"Рассылка завершена: ✅ Успешно: {success}, ❌ Не удалось: {failed}", 'success')
        return redirect(url_for('broadcast'))
    
    return render_template('broadcast.html')

# HTML Templates
TEMPLATES = {
    'index.html': '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>WARP Bot Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-100 font-sans">
        <div class="flex h-screen">
            <!-- Sidebar -->
            <div class="w-64 bg-gray-800 text-white p-6">
                <h2 class="text-2xl font-bold mb-8">WARP Bot</h2>
                <nav>
                    <a href="{{ url_for('index') }}" class="block py-2 px-4 rounded bg-blue-600 mb-2">Главная</a>
                    <a href="{{ url_for('users') }}" class="block py-2 px-4 rounded hover:bg-gray-700 mb-2">Пользователи</a>
                    <a href="{{ url_for('broadcast') }}" class="block py-2 px-4 rounded hover:bg-gray-700 mb-2">Рассылка</a>
                    <a href="{{ url_for('logout') }}" class="block py-2 px-4 rounded hover:bg-gray-700">Выйти</a>
                </nav>
            </div>
            <!-- Main Content -->
            <div class="flex-1 p-8">
                <h1 class="text-3xl font-bold mb-6">Главная</h1>
                {% for message in get_flashed_messages(with_categories=true) %}
                    <div class="bg-{% if message[0] == 'success' %}green{% elif message[0] == 'error' %}red{% else %}yellow{% endif %}-100 border-{% if message[0] == 'success' %}green{% elif message[0] == 'error' %}red{% else %}yellow{% endif %}-400 text-{% if message[0] == 'success' %}green{% elif message[0] == 'error' %}red{% else %}yellow{% endif %}-700 px-4 py-3 rounded relative mb-4" role="alert">
                        {{ message[1] }}
                    </div>
                {% endfor %}
                <div class="bg-white p-6 rounded-lg shadow-md mb-6">
                    <h2 class="text-xl font-semibold mb-4">Статус Telegram API</h2>
                    <p class="{% if api_status.connected %}text-green-600{% else %}text-red-600{% endif %} font-medium">{{ api_status.message }}</p>
                </div>
                <div class="bg-white p-6 rounded-lg shadow-md">
                    <h2 class="text-xl font-semibold mb-4">Статистика</h2>
                    <pre class="bg-gray-100 p-4 rounded-lg">{{ stats_text }}</pre>
                </div>
            </div>
        </div>
    </body>
    </html>
    ''',
    'login.html': '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Login - WARP Bot</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-100 flex items-center justify-center h-screen">
        <div class="bg-white p-8 rounded-lg shadow-md w-full max-w-md">
            <h1 class="text-2xl font-bold mb-6 text-center">Вход в WARP Bot</h1>
            {% for message in get_flashed_messages(with_categories=true) %}
                <div class="bg-{% if message[0] == 'success' %}green{% elif message[0] == 'error' %}red{% else %}yellow{% endif %}-100 border-{% if message[0] == 'success' %}green{% elif message[0] == 'error' %}red{% else %}yellow{% endif %}-400 text-{% if message[0] == 'success' %}green{% elif message[0] == 'error' %}red{% else %}yellow{% endif %}-700 px-4 py-3 rounded relative mb-4" role="alert">
                    {{ message[1] }}
                </div>
            {% endfor %}
            <form method="POST">
                <div class="mb-4">
                    <label for="username" class="block text-sm font-medium text-gray-700">Имя пользователя</label>
                    <input type="text" id="username" name="username" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500" required>
                </div>
                <div class="mb-6">
                    <label for="password" class="block text-sm font-medium text-gray-700">Пароль</label>
                    <input type="password" id="password" name="password" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500" required>
                </div>
                <button type="submit" class="w-full bg-blue-600 text-white py-2 px-4 rounded-md hover:bg-blue-700 transition duration-200">Войти</button>
            </form>
        </div>
    </body>
    </html>
    ''',
    'users.html': '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Users - WARP Bot</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-100 font-sans">
        <div class="flex h-screen">
            <!-- Sidebar -->
            <div class="w-64 bg-gray-800 text-white p-6">
                <h2 class="text-2xl font-bold mb-8">WARP Bot</h2>
                <nav>
                    <a href="{{ url_for('index') }}" class="block py-2 px-4 rounded hover:bg-gray-700 mb-2">Главная</a>
                    <a href="{{ url_for('users') }}" class="block py-2 px-4 rounded bg-blue-600 mb-2">Пользователи</a>
                    <a href="{{ url_for('broadcast') }}" class="block py-2 px-4 rounded hover:bg-gray-700 mb-2">Рассылка</a>
                    <a href="{{ url_for('logout') }}" class="block py-2 px-4 rounded hover:bg-gray-700">Выйти</a>
                </nav>
            </div>
            <!-- Main Content -->
            <div class="flex-1 p-8">
                <h1 class="text-3xl font-bold mb-6">Пользователи</h1>
                {% for message in get_flashed_messages(with_categories=true) %}
                    <div class="bg-{% if message[0] == 'success' %}green{% elif message[0] == 'error' %}red{% else %}yellow{% endif %}-100 border-{% if message[0] == 'success' %}green{% elif message[0] == 'error' %}red{% else %}yellow{% endif %}-400 text-{% if message[0] == 'success' %}green{% elif message[0] == 'error' %}red{% else %}yellow{% endif %}-700 px-4 py-3 rounded relative mb-4" role="alert">
                        {{ message[1] }}
                    </div>
                {% endfor %}
                <div class="bg-white p-6 rounded-lg shadow-md">
                    <table class="min-w-full divide-y divide-gray-200">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Username</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Имя</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Статус</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Действия</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
                            {% for user in users %}
                            <tr>
                                <td class="px-6 py-4 whitespace-nowrap">{{ user[0] }}</td>
                                <td class="px-6 py-4 whitespace-nowrap">{{ user[1] or 'N/A' }}</td>
                                <td class="px-6 py-4 whitespace-nowrap">{{ user[2] or 'N/A' }}</td>
                                <td class="px-6 py-4 whitespace-nowrap">{{ 'Забанен' if user[3] else 'Активен' }}</td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    {% if user[3] %}
                                    <a href="{{ url_for('unban_user', user_id=user[0]) }}" class="text-green-600 hover:text-green-800">Разбанить</a>
                                    {% else %}
                                    <a href="{{ url_for('ban_user', user_id=user[0]) }}" class="text-red-600 hover:text-red-800">Забанить</a>
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </body>
    </html>
    ''',
    'broadcast.html': '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Broadcast - WARP Bot</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-100 font-sans">
        <div class="flex h-screen">
            <!-- Sidebar -->
            <div class="w-64 bg-gray-800 text-white p-6">
                <h2 class="text-2xl font-bold mb-8">WARP Bot</h2>
                <nav>
                    <a href="{{ url_for('index') }}" class="block py-2 px-4 rounded hover:bg-gray-700 mb-2">Главная</a>
                    <a href="{{ url_for('users') }}" class="block py-2 px-4 rounded hover:bg-gray-700 mb-2">Пользователи</a>
                    <a href="{{ url_for('broadcast') }}" class="block py-2 px-4 rounded bg-blue-600 mb-2">Рассылка</a>
                    <a href="{{ url_for('logout') }}" class="block py-2 px-4 rounded hover:bg-gray-700">Выйти</a>
                </nav>
            </div>
            <!-- Main Content -->
            <div class="flex-1 p-8">
                <h1 class="text-3xl font-bold mb-6">Рассылка пользователям</h1>
                {% for message in get_flashed_messages(with_categories=true) %}
                    <div class="bg-{% if message[0] == 'success' %}green{% elif message[0] == 'error' %}red{% else %}yellow{% endif %}-100 border-{% if message[0] == 'success' %}green{% elif message[0] == 'error' %}red{% else %}yellow{% endif %}-400 text-{% if message[0] == 'success' %}green{% elif message[0] == 'error' %}red{% else %}yellow{% endif %}-700 px-4 py-3 rounded relative mb-4" role="alert">
                        {{ message[1] }}
                    </div>
                {% endfor %}
                <div class="bg-white p-6 rounded-lg shadow-md">
                    <form method="POST">
                        <div class="mb-4">
                            <label for="message" class="block text-sm font-medium text-gray-700">Сообщение для рассылки</label>
                            <textarea id="message" name="message" rows="5" class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500" required></textarea>
                        </div>
                        <button type="submit" class="bg-blue-600 text-white py-2 px-4 rounded-md hover:bg-blue-700 transition duration-200">Отправить рассылку</button>
                    </form>
                </div>
            </div>
        </div>
    </body>
    </html>
    '''
}

# Создание шаблонов
import os
os.makedirs('templates', exist_ok=True)
for filename, content in TEMPLATES.items():
    with open(os.path.join('templates', filename), 'w', encoding='utf-8') as f:
        f.write(content)

# Telegram Bot Handlers
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
        await get_config(query, context)
    elif data == "help":
        await help_command(query, context)
    elif data == "stats" and is_admin(user.id):
        await stats_command(query, context)
    elif data == "users" and is_admin(user.id):
        await users_command(query, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    
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

async def get_config(query: Update, context: ContextTypes.DEFAULT_TYPE):
    user = query.from_user
    
    if db.is_banned(user.id):
        await query.message.reply_text("❌ Вы забанены и не можете получать конфигурации.")
        return
    
    if not db.can_get_config(user.id):
        await query.message.reply_text(
            "⏳ Вы можете запрашивать конфигурацию только раз в 24 часа. "
            "Попробуйте позже."
        )
        return
    
    config = generate_warp_config()
    db.add_config(user.id)
    
    config_file = f"warp_{user.id}.conf"
    with open(config_file, "w", encoding='utf-8') as f:
        f.write(config)
    
    with open(config_file, "rb") as f:
        await context.bot.send_document(
            chat_id=user.id,
            document=f,
            filename="warp.conf",
            caption="Ваша WARP конфигурация"
        )
    
    os.remove(config_file)
    
    logger.info(f"Пользователь {user.id} получил конфигурацию")

async def stats_command(query: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(query.from_user.id):
        await query.message.reply_text("❌ Эта команда только для администратора.")
        return
    
    active_users, banned_users, active_configs, total_configs = db.get_stats()
    
    response = (
        "📊 Статистика бота:\n\n"
        f"👥 Пользователи: {active_users} активных, {banned_users} забаненных\n"
        f"📂 Конфигурации: {active_configs} активных, {total_configs} всего"
    )
    
    await query.message.reply_text(response)

async def users_command(query: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(query.from_user.id):
        await query.message.reply_text("❌ Эта команда только для администратора.")
        return
    
    users = db.get_users_list()
    if not users:
        await query.message.reply_text("Нет пользователей в базе данных.")
        return
    
    response = "👥 Последние 50 пользователей:\n\n"
    for user in users:
        status = "🚫" if user[3] else "✅"
        response += f"{status} ID: {user[0]}, Username: @{user[1] or 'N/A'}, Имя: {user[2] or 'N/A'}\n"
    
    await query.message.reply_text(response)

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
        
        if (success + failed) % 10 == 0:
            await progress_msg.edit_text(
                f"Рассылка в процессе...\n"
                f"✅ Успешно: {success}\n"
                f"❌ Не удалось: {failed}"
            )
        
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

# Запуск Flask в отдельном потоке
def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False)

# Основная функция
def main():
    global application
    # Запуск Telegram-бота
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Запуск Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("getconfig", get_config))
    
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    
    application.add_handler(CallbackQueryHandler(button_handler))
    
    application.add_error_handler(error_handler)
    
    application.run_polling()

if __name__ == "__main__":
    main()
