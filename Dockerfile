FROM python:slim

# Установка рабочей директории
WORKDIR /app

# Установка переменной окружения
ENV PYTHONUNBUFFERED=1

# Установка только необходимых системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends bash \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Установка Python-зависимостей
RUN pip install --no-cache-dir --upgrade log2telegram

# Копирование скрипта
COPY docker-runner-bot.sh /app/docker-runner-bot.sh

# Сделать скрипт исполняемым
RUN chmod +x /app/docker-runner-bot.sh

# Определение команды запуска
CMD ["/bin/bash", "/app/docker-runner-bot.sh"]