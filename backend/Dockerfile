FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (falls pandas/Numpy/fastf1 sie brauchen)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libatlas-base-dev gfortran wget && \
    rm -rf /var/lib/apt/lists/*

# Requirements
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY backend/ /app/

# FastF1 Cache Pfad via ENV (dein Code sollte das nutzen!)
ENV FASTF1_CACHE=/data/fastf1_cache
VOLUME ["/data/fastf1_cache", "/app/app/season_cache"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host=0.0.0.0", "--port=8000"]
