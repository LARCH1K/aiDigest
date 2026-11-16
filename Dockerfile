# Образ API и встроенного сборщика aiDigest.
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONPATH=/app/src \
    TZ=Asia/Yekaterinburg \
    AIDIGEST_DATA_DIR=/data

WORKDIR /app

# Сначала зависимости — этот слой кешируется, пока не меняется requirements.lock
COPY requirements.lock .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.lock

# Код, миграции и ресурсы для запуска API и тестов.
COPY src/ src/
COPY config/ config/
COPY eval/ eval/
COPY tests/ tests/
COPY alembic.ini pyproject.toml ./

EXPOSE 8000
CMD ["python", "-m", "aidigest_api", "--host", "0.0.0.0", "--port", "8000"]
