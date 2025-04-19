import sqlite3
from datetime import datetime, timedelta
import uuid

def add_test_data():
    try:
        conn = sqlite3.connect("warp_bot.db")
        c = conn.cursor()
        for i in range(10):
            telegram_id = 12345 + i
            c.execute(
                "INSERT OR IGNORE INTO users (telegram_id, username, first_name, first_seen, is_banned) "
                "VALUES (?, ?, ?, ?, ?)",
                (telegram_id, f"test_user_{i}", f"User{i}", datetime.now() - timedelta(hours=i), 0)
            )
            c.execute(
                "INSERT INTO configs (config_id, telegram_id, created_at, is_active) "
                "VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), telegram_id, datetime.now() - timedelta(hours=i), 1)
            )
        conn.commit()
        print("Тестовые данные успешно добавлены.")
    except sqlite3.Error as e:
        print(f"Ошибка добавления данных: {e}")
        raise
    finally:
        conn.close()

def verify_data():
    try:
        conn = sqlite3.connect("warp_bot.db")
        c = conn.cursor()
        c.execute("SELECT * FROM users")
        users = c.fetchall()
        c.execute("SELECT * FROM configs")
        configs = c.fetchall()
        print("Пользователи:", users)
        print("Конфигурации:", configs)
        conn.close()
    except sqlite3.Error as e:
        print(f"Ошибка проверки данных: {e}")

if __name__ == "__main__":
    add_test_data()
    verify_data()
