# Образ aidigest: веб-интерфейс и сборщик (worker) из одного образа.
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONPATH=/app/src \
    TZ=Asia/Yekaterinburg

WORKDIR /app

# Сначала зависимости — этот слой кешируется, пока не меняется requirements.lock
COPY requirements.lock .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.lock

# Код в /app/src, конфиги в /app/config: ROOT = parents[2] указывает на /app
COPY . .

CMD ["python", "-m", "aidigest_web", "--host", "0.0.0.0", "--port", "8000"]
