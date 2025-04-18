import sqlite3
import os
import logging
import argparse
import shutil
import asyncio
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
from jinja2 import Environment, FileSystemLoader

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

# Папки для статических файлов и шаблонов
STATIC_DIR = "/tmp/static"
TEMPLATE_DIR = "/tmp/templates"
REPO_STATIC_DIR = os.path.join(os.getcwd(), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATE_DIR, exist_ok=True)
os.makedirs(REPO_STATIC_DIR, exist_ok=True)

# Инициализация Jinja2
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

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
        generate_site()  # Обновляем сайт после регистрации
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
        generate_site()  # Обновляем сайт после изменения статуса
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

# Построение графика активности
def plot_hourly_activity():
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

    plot_path = os.path.join(STATIC_DIR, "hourly_activity.png")
    plt.savefig(plot_path, bbox_inches='tight')
    plt.close()
    return plot_path

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

# Генерация HTML для сайта
def generate_site():
    try:
        # Получаем статистику
        active_users, banned_users = get_stats()
        plot_path = plot_hourly_activity()

        # Создаем шаблон HTML
        template_str = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>WARP Bot Statistics</title>
            <link rel="stylesheet" href="styles.css">
        </head>
        <body>
            <div class="container">
                <h1>WARP Bot Statistics</h1>
                <p><strong>Active Users:</strong> {{ active_users }}</p>
                <p><strong>Banned Users:</strong> {{ banned_users }}</p>
                <h2>Hourly Activity (Last 24 Hours)</h2>
                {% if plot_path %}
                <img src="hourly_activity.png" alt="Hourly Activity Graph">
                {% else %}
                <p>No activity data available for the last 24 hours.</p>
                {% endif %}
            </div>
        </body>
        </html>
        """
        # Сохраняем шаблон
        template_path = os.path.join(TEMPLATE_DIR, "index.html")
        with open(template_path, "w") as f:
            f.write(template_str)

        # Рендерим HTML
        template = env.get_template("index.html")
        html_content = template.render(
            active_users=active_users,
            banned_users=banned_users,
            plot_path=plot_path
        )

        # Сохраняем HTML
        html_path = os.path.join(STATIC_DIR, "index.html")
        with open(html_path, "w") as f:
            f.write(html_content)

        # Создаем CSS
        css_content = """
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
        """
        css_path = os.path.join(STATIC_DIR, "styles.css")
        with open(css_path, "w") as f:
            f.write(css_content)

        # Копируем файлы в static/ для деплоя
        shutil.copy(html_path, REPO_STATIC_DIR)
        shutil.copy(css_path, REPO_STATIC_DIR)
        if plot_path and os.path.exists(plot_path):
            shutil.copy(plot_path, REPO_STATIC_DIR)

        logger.info(f"Сайт сгенерирован: {html_path}")
        return html_path
    except Exception as e:
        logger.error(f"Ошибка генерации сайта: {e}")
        return None

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
            "/updatesite - Обновить статистику на сайте"
        )
        await query.message.reply_text(help_text, reply_markup=reply_markup)
    elif query.data == "hourly_activity" and is_admin_user:
        plot_path = plot_hourly_activity()
        if not plot_path or not os.path.exists(plot_path):
            await query.message.reply_text(
                "Не удалось создать график. Нет данных за последние 24 часа.",
                reply_markup=reply_markup,
            )
            return
        try:
            with open(plot_path, 'rb') as photo:
                await query.message.reply_photo(photo=photo, reply_markup=reply_markup)
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

    plot_path = plot_hourly_activity()
    reply_markup = get_main_keyboard(is_admin=True)
    if not plot_path or not os.path.exists(plot_path):
        await update.message.reply_text(
            "Не удалось создать график. Нет данных за последние 24 часа.",
            reply_markup=reply_markup,
        )
        return

    try:
        with open(plot_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка отправки графика: {e}")
        await update.message.reply_text("Ошибка при отправке графика.", reply_markup=reply_markup)

# Обработчик команды /updatesite
async def update_site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    html_path = generate_site()
    reply_markup = get_main_keyboard(is_admin=True)
    if not html_path or not os.path.exists(html_path):
        await update.message.reply_text(
            "Ошибка при генерации сайта.", reply_markup=reply_markup
        )
        return

    await update.message.reply_text(
        f"Сайт успешно обновлен: {html_path}\nПроверьте: https://warpxc.onrender.com\n"
        "Для публикации запустите GitHub Actions workflow.",
        reply_markup=reply_markup
    )

# Основная функция
async def main():
    try:
        init_db()
        generate_site()  # Инициализируем сайт при запуске
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
        application.add_handler(CommandHandler("updatesite", update_site))

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
                    retry_delay *= 2  # Экспоненциальная задержка
                else:
                    logger.error("Не удалось устранить конфликт getUpdates. Завершение работы.")
                    raise
            except Exception as e:
                logger.error(f"Ошибка запуска бота: {e}")
                raise
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-site", action="store_true", help="Update site files")
    args = parser.parse_args()

    if args.update_site:
        init_db()
        html_path = generate_site()
        if html_path:
            print(f"Site updated: {html_path}")
        else:
            print("Failed to update site")
    else:
        asyncio.run(main())
