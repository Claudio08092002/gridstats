FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# pip aktualisieren (holt stabile Wheels für numpy/pandas)
RUN python -m pip install --upgrade pip

# Requirements zuerst kopieren → bessere Layer-Caches
COPY backend/requirements.txt /app/requirements.txt

# Nur Wheels verwenden, keine Source-Builds (kein gcc nötig)
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

# App-Code kopieren
COPY backend/ /app/

# Cache-Pfade
ENV FASTF1_CACHE=/data/fastf1_cache
VOLUME ["/data/fastf1_cache", "/app/app/season_cache"]

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host=0.0.0.0", "--port=8000", "--access-log"]
