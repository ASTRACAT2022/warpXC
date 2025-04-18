import sqlite3
import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import pandas as pd

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
        # Предполагаем, что поле first_seen содержит временные метки действий
        query = """
            SELECT strftime('%H', first_seen) as hour, COUNT(*) as activity_count
            FROM users
            WHERE first_seen >= ?
            GROUP BY hour
            ORDER BY hour
        """
        # Период анализа: последние 24 часа
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

    # Создаем график
    plt.figure(figsize=(10, 6))
    plt.bar(df['hour'], df['activity_count'], color='skyblue')
    plt.xlabel('Час дня')
    plt.ylabel('Количество действий')
    plt.title('Активность пользователей по часам (последние 24 часа)')
    plt.xticks(range(24))
    plt.grid(True, axis='y', linestyle='--', alpha=0.7)

    # Сохраняем график как изображение
    plot_path = "hourly_activity.png"
    plt.savefig(plot_path, bbox_inches='tight')
    plt.close()
    return plot_path

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username)

    keyboard = [
        [
            InlineKeyboardButton("Получить конфиг", callback_data="get_config"),
            InlineKeyboardButton("Справка", callback_data="help"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Привет! Я бот для управления конфигурациями WARP. Выбери действие:",
        reply_markup=reply_markup,
    )

# Обработчик кнопок
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "get_config":
        await query.message.reply_text(
            "Вот пример конфигурации WARP:\n\n[Interface]\nPrivateKey = your_private_key\nAddress = 192.168.1.1\nDNS = 1.1.1.1\n\n[Peer]\nPublicKey = peer_public_key\nEndpoint = 162.159.192.1:2408\nAllowedIPs = 0.0.0.0/0"
        )
    elif query.data == "help":
        await query.message.reply_text(
            "Я бот для управления WARP. Доступные команды:\n/start - Начать работу\n/getconfig - Получить конфигурацию\nДля админов:\n/stats - Статистика\n/users - Список пользователей\n/ban <user_id> - Забанить\n/unban <user_id> - Разбанить\n/broadcast <сообщение> - Рассылка\n/hourly_activity - График активности по часам"
        )

# Обработчик команды /getconfig
async def get_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Вот пример конфигурации WARP:\n\n[Interface]\nPrivateKey = your_private_key\nAddress = 192.168.1.1\nDNS = 1.1.1.1\n\n[Peer]\nPublicKey = peer_public_key\nEndpoint = 162.159.192.1:2408\nAllowedIPs = 0.0.0.0/0"
    )

# Обработчик команды /stats
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    active_users, banned_users = get_stats()
    await update.message.reply_text(
        f"Статистика:\nАктивных пользователей: {active_users}\nЗабаненных пользователей: {banned_users}"
    )

# Обработчик команды /users
async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    user_list = get_users()
    if not user_list:
        await update.message.reply_text("Пользователи не найдены.")
        return

    response = "Список пользователей:\n"
    for user in user_list:
        status = "Забанен" if user[2] else "Активен"
        response += f"ID: {user[0]}, Username: {user[1] or 'N/A'}, Статус: {status}\n"
    await update.message.reply_text(response)

# Обработчик команды /ban
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    try:
        user_id = int(context.args[0])
        set_ban_status(user_id, 1)
        await update.message.reply_text(f"Пользователь ID {user_id} забанен.")
        # Уведомление пользователю
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="Вы были забанены администратором.",
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить пользователя ID {user_id}: {e}")
    except (IndexError, ValueError):
        await update.message.reply_text("Использование: /ban <user_id>")

# Обработчик команды /unban
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    try:
        user_id = int(context.args[0])
        set_ban_status(user_id, 0)
        await update.message.reply_text(f"Пользователь ID {user_id} разбанен.")
        # Уведомление пользователю
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="Вы были разбанены администратором.",
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить пользователя ID {user_id}: {e}")
    except (IndexError, ValueError):
        await update.message.reply_text("Использование: /unban <user_id>")

# Обработчик команды /broadcast
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /broadcast <сообщение>")
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
        f"Рассылка завершена. Сообщение отправлено {success_count} пользователям."
    )

# Обработчик команды /hourly_activity
async def hourly_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администратору.")
        return

    plot_path = plot_hourly_activity()
    if not plot_path or not os.path.exists(plot_path):
        await update.message.reply_text("Не удалось создать график. Нет данных за последние 24 часа.")
        return

    try:
        with open(plot_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo)
        os.remove(plot_path)  # Удаляем временный файл
    except Exception as e:
        logger.error(f"Ошибка отправки графика: {e}")
        await update.message.reply_text("Ошибка при отправке графика.")

# Основная функция
def main():
    try:
        init_db()
        application = Application.builder().token(BOT_TOKEN).build()

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

        # Запуск бота
        logger.info("Бот запущен.")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
        raise

if __name__ == "__main__":
    main()
