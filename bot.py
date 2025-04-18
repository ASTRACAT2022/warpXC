import sqlite3
import os
import logging
import asyncio
import threading
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.error import Conflict
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import pandas as pd
from flask import Flask, render_template_string, send_file
import io
from telegram.ext._application import Application

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
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

# Инициализация Flask
app = Flask(__name__)

# Инициализация базы данных
def init_db():
    try:
        conn = sqlite3.connect("warp_bot.db")
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_seen DATETIME,
                is_banned INTEGER DEFAULT 0
            )
        """
        )
        conn.commit()
        logger.info("База данных инициализирована успешно.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")
        raise
    finally:
        conn.close()

# Проверка, является ли пользователь админом
def is_admin(user_id):
    return user_id == ADMIN_TELEGRAM_ID

# Регистрация пользователя
def register_user(user_id, username):
    try:
        conn = sqlite3.connect("warp_bot.db")
        c = conn.cursor()
        c.execute(
            """
            INSERT OR IGNORE INTO users (user_id, username, first_seen)
            VALUES (?, ?, ?)
        """,
            (user_id, username, datetime.now()),
        )
        conn.commit()
        logger.info(f"Пользователь {username} (ID: {user_id}) зарегистрирован.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка регистрации пользователя: {e}")
    finally:
        conn.close()

# Получение статистики
def get_stats():
    try:
        conn = sqlite3.connect("warp_bot.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0")
        active_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
        banned_users = c.fetchone()[0]
        return active_users, banned_users
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения статистики: {e}")
        return 0, 0
    finally:
        conn.close()

# Получение списка пользователей
def get_users():
    try:
        conn = sqlite3.connect("warp_bot.db")
        c = conn.cursor()
        c.execute("SELECT user_id, username, is_banned FROM users")
        return c.fetchall()
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения списка пользователей: {e}")
        return []
    finally:
        conn.close()

# Бан/разбан пользователя
def set_ban_status(user_id, ban_status):
    try:
        conn = sqlite3.connect("warp_bot.db")
        c = conn.cursor()
        c.execute(
            "UPDATE users SET is_banned = ? WHERE user_id = ?",
            (ban_status, user_id),
        )
        conn.commit()
        logger.info(f"Пользователь ID {user_id} {'забанен' if ban_status else 'разбанен'}.")
    except sqlite3.Error as e:
        logger.error(f"Ошибка изменения статуса бана: {e}")
    finally:
        conn.close()

# Анализ активности пользователей по часам
def get_hourly_activity():
    try:
        conn = sqlite3.connect("warp_bot.db")
        query = """
            SELECT strftime('%H', first_seen) as hour, COUNT(*) as activity_count
            FROM users
            WHERE first_seen >= ?
            GROUP BY hour
            ORDER BY hour
        """
        start_time = datetime.now() - timedelta(days=1)
        df = pd.read_sql_query(query, conn, params=(start_time,))
        return df
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения данных активности: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

# Генерация графика активности
def generate_activity_plot():
    df = get_hourly_activity()
    if df.empty:
        return None

    plt.figure(figsize=(10, 6))
    plt.bar(df['hour'], df['activity_count'], color='skyblue')
    plt.xlabel('Час дня')
    plt.ylabel('Количество действий')
    plt.title('Активность пользователей по часам (последние 24 часа)')
    plt.xticks(range(24))
    plt.grid(True, axis='y', linestyle='--', alpha=0.7)

    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight')
    buffer.seek(0)
    plt.close()
    return buffer

# Генерация конфигурации WARP
def generate_warp_config(user_id):
    try:
        config = (
            "[Interface]\n"
            "PrivateKey = CS/UQwV5cCjhGdH/1FQbSkRLvYU8Ha1xeTkHVg5rizI=\n"
            "S1 = 0\n"
            "S2 = 0\n"
            "Jc = 120\n"
            "Jmin = 23\n"
            "Jmax = 911\n"
            "H1 = 1\n"
            "H2 = 2\n"
            "H3 = 3\n"
            "H4 = 4\n"
            "MTU = 1280\n"
            "Address = 172.16.0.2, 2606:4700:110:8a82:ae4c:ce7e:e5a6:a7fd\n"
            "DNS = 1.1.1.1, 2606:4700:4700::1111, 1.0.0.1, 2606:4700:4700::1001\n\n"
            "[Peer]\n"
            "PublicKey = bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=\n"
            "AllowedIPs = 0.0.0.0/0, ::/0\n"
            "Endpoint = 162.159.192.227:894"
        )
        config_path = f"/tmp/warp_config_{user_id}.conf"
        with open(config_path, "w") as f:
            f.write(config)
        return config_path
    except Exception as e:
        logger.error(f"Ошибка генерации конфигурации: {e}")
        return None

# Flask маршрут для главной страницы
@app.route('/')
def stats_page():
    active_users, banned_users = get_stats()
    return render_template_string(
        """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>WARP Bot Statistics</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    background-color: #f0f0f0;
                    margin: 0;
                    padding: 20px;
                }
                .container {
                    max-width: 800px;
                    margin: 0 auto;
                    background-color: #fff;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 0 10px rgba(0,0,0,0.1);
                }
                h1, h2 {
                    color: #333;
                }
                p {
                    font-size: 16px;
                    color: #555;
                }
                img {
                    max-width: 100%;
                    height: auto;
                    margin-top: 20px;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>WARP Bot Statistics</h1>
                <p><strong>Active Users:</strong> {{ active_users }}</p>
                <p><strong>Banned Users:</strong> {{ banned_users }}</p>
                <h2>Hourly Activity (Last 24 Hours)</h2>
                <img src="/activity_plot" alt="Hourly Activity Graph">
            </div>
        </body>
        </html>
        """,
        active_users=active_users,
        banned_users=banned_users
    )

# Flask маршрут для графика активности
@app.route('/activity_plot')
def activity_plot():
    plot_buffer = generate_activity_plot()
    if not plot_buffer:
        return "No activity data available for the last 24 hours.", 404
    return send_file(plot_buffer, mimetype='image/png')

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
        keyboard.append([InlineKeyboardButton("Активность по часам", callback_data="hourly_activity")])
    return InlineKeyboardMarkup(keyboard)

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username)

    is_admin_user = is_admin(user.id)
    reply_markup = get_main_keyboard(is_admin_user)
    welcome_message = (
        f"Привет, {user.first_name or 'пользователь'}! 👋\n"
        f"Ваш Telegram ID: {user.id}\n"
        "Я бот для управления конфигурациями WARP. Выбери действие:"
    )
    await update.message.reply_text(welcome_message, reply_markup=reply_markup)

# Обработчик кнопок
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    is_admin_user = is_admin(user.id)
    reply_markup = get_main_keyboard(is_admin_user)

    await query.answer()

    if query.data == "get_config":
        config_path = generate_warp_config(user.id)
        if not config_path or not os.path.exists(config_path):
            await query.message.reply_text(
                "Ошибка при генерации конфигурации.", reply_markup=reply_markup
            )
            return
        try:
            with open(config_path, 'rb') as config_file:
                await query.message.reply_document(
                    document=config_file,
                    filename=f"warp_config_{user.id}.conf",
                    caption="Ваша конфигурация WARP",
                    reply_markup=reply_markup
                )
            os.remove(config_path)
        except Exception as e:
            logger.error(f"Ошибка отправки конфигурации: {e}")
            await query.message.reply_text(
                "Ошибка при отправке конфигурации.", reply_markup=reply_markup
            )
    elif query.data == "help":
        help_text = (
            "Я бот для управления WARP. Доступные команды:\n"
            "/start - Начать работу\n"
            "/getconfig - Получить конфигурацию WARP (.conf файл)\n"
            "Для админов:\n"
            "/stats - Статистика\n"
            "/users - Список пользователей\n"
            "/ban <user_id> - Забанить\n"
            "/unban <user_id> - Разбанить\n"
            "/broadcast <сообщение> - Рассылка\n"
            "/hourly_activity - График активности по часам\n"
        )
        await query.message.reply_text(help_text, reply_markup=reply_markup)
    elif query.data == "hourly_activity" and is_admin_user:
        plot_buffer = generate_activity_plot()
        if not plot_buffer:
            await query.message.reply_text(
                "Не удалось создать график. Нет данных за последние 24 часа.",
                reply_markup=reply_markup,
            )
            return
        try:
            await query.message.reply_photo(photo=plot_buffer, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Ошибка отправки графика: {e}")
            await query.message.reply_text("Ошибка при отправке графика.", reply_markup=reply_markup)

# Обработчик команды /getconfig
async def get_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin_user = is_admin(user.id)
    reply_markup = get_main_keyboard(is_admin_user)

    config_path = generate_warp_config(user.id)
    if not config_path or not os.path.exists(config_path):
        await update.message.reply_text(
            "Ошибка при генерации конфигурации.", reply_markup=reply_markup
        )
        return
    try:
        with open(config_path, 'rb') as config_file:
            await update.message.reply_document(
                document=config_file,
                filename=f"warp_config_{user.id}.conf",
                caption="Ваша конфигурация WARP",
                reply_markup=reply_markup
            )
        os.remove(config_path)
    except Exception as e:
        logger.error(f"Ошибка отправки конфигурации: {e}")
        await update.message.reply_text(
            "Ошибка при отправке конфигурации.", reply_markup=reply_markup
        )

# Обработчик команды /stats
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    active_users, banned_users = get_stats()
    reply_markup = get_main_keyboard(is_admin=True)
    await update.message.reply_text(
        f"Статистика:\nАктивных пользователей: {active_users}\nЗабаненных пользователей: {banned_users}",
        reply_markup=reply_markup,
    )

# Обработчик команды /users
async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    user_list = get_users()
    if not user_list:
        await update.message.reply_text("Пользователи не найдены.", reply_markup=get_main_keyboard(is_admin=True))
        return

    response = "Список пользователей:\n"
    for user in user_list:
        status = "Забанен" if user[2] else "Активен"
        response += f"ID: {user[0]}, Username: {user[1] or 'N/A'}, Статус: {status}\n"
    await update.message.reply_text(response, reply_markup=get_main_keyboard(is_admin=True))

# Обработчик команды /ban
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    try:
        user_id = int(context.args[0])
        set_ban_status(user_id, 1)
        await update.message.reply_text(
            f"Пользователь ID {user_id} забанен.",
            reply_markup=get_main_keyboard(is_admin=True),
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="Вы были забанены администратором.",
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить пользователя ID {user_id}: {e}")
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Использование: /ban <user_id>",
            reply_markup=get_main_keyboard(is_admin=True),
        )

# Обработчик команды /unban
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    try:
        user_id = int(context.args[0])
        set_ban_status(user_id, 0)
        await update.message.reply_text(
            f"Пользователь ID {user_id} разбанен.",
            reply_markup=get_main_keyboard(is_admin=True),
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="Вы были разбанены администратором.",
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить пользователя ID {user_id}: {e}")
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Использование: /unban <user_id>",
            reply_markup=get_main_keyboard(is_admin=True),
        )

# Обработчик команды /broadcast
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    if not context.args:
        await update.message.reply_text(
            "Использование: /broadcast <сообщение>",
            reply_markup=get_main_keyboard(is_admin=True),
        )
        return

    message = " ".join(context.args)
    user_list = get_users()
    success_count = 0
    for user in user_list:
        if not user[2]:  # Пропускаем забаненных
            try:
                await context.bot.send_message(
                    chat_id=user[0],
                    text=message,
                )
                success_count += 1
            except Exception as e:
                logger.warning(f"Не удалось отправить сообщение пользователю ID {user[0]}: {e}")
    await update.message.reply_text(
        f"Рассылка завершена. Сообщение отправлено {success_count} пользователям.",
        reply_markup=get_main_keyboard(is_admin=True),
    )

# Обработчик команды /hourly_activity
async def hourly_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    plot_buffer = generate_activity_plot()
    reply_markup = get_main_keyboard(is_admin=True)
    if not plot_buffer:
        await update.message.reply_text(
            "Не удалось создать график. Нет данных за последние 24 часа.",
            reply_markup=reply_markup,
        )
        return

    try:
        await update.message.reply_photo(photo=plot_buffer, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка отправки графика: {e}")
        await update.message.reply_text("Ошибка при отправке графика.", reply_markup=reply_markup)

# Запуск Telegram-бота
async def run_bot():
    try:
        init_db()
        application = Application.builder().token(BOT_TOKEN).build()

        # Явно отключаем webhook
        try:
            await application.bot.delete_webhook(drop_pending_updates=True)
            logger.info("Webhook успешно отключен.")
        except Exception as e:
            logger.error(f"Ошибка при отключении webhook: {e}")

        # Регистрация обработчиков
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(button))
        application.add_handler(CommandHandler("getconfig", get_config))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("users", users))
        application.add_handler(CommandHandler("ban", ban))
        application.add_handler(CommandHandler("unban", unban))
        application.add_handler(CommandHandler("broadcast", broadcast))
        application.add_handler(CommandHandler("hourly_activity", hourly_activity))

        # Запуск бота с обработкой конфликтов
        max_retries = 3
        retry_delay = 5
        for attempt in range(max_retries):
            try:
                await application.initialize()
                await application.start()
                logger.info("Бот запущен.")
                await application.updater.start_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True
                )
                await application.run_polling()
                break
            except Conflict as e:
                logger.warning(f"Конфликт getUpdates (попытка {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error("Не удалось устранить конфликт getUpdates. Завершение работы.")
                    raise
            except Exception as e:
                logger.error(f"Ошибка запуска бота: {e}")
                raise
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        raise

# Запуск Flask и Telegram-бота
def main():
    # Запускаем Telegram-бот в отдельном потоке
    bot_thread = threading.Thread(target=lambda: asyncio.run(run_bot()))
    bot_thread.daemon = True
    bot_thread.start()

    # Запускаем Flask
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))

if __name__ == "__main__":
    main()
