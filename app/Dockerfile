FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем всё содержимое папки приложения
COPY . .

# Команда для запуска FastAPI
# host 0.0.0.0 обязателен для Docker, чтобы порт "пробрасывался" наружу
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]