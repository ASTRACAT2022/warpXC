FROM python:3.9

# Установка системных зависимостей для matplotlib
RUN apt-get update && apt-get install -y \
    libpng-dev \
    libfreetype6-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Установка Python-зависимостей
RUN pip install --no-cache-dir python-telegram-bot python-dotenv matplotlib

CMD ["python", "bot.py"]
