FROM python:3.11-slim

# Prevent Python from writing pyc files to disk and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set working directory inside the container
WORKDIR /app

# Upgrade pip to get stable wheels for numpy/pandas
RUN python -m pip install --upgrade pip

# Copy requirements first to leverage Docker layer caching
COPY backend/requirements.txt /app/requirements.txt

# Install Python dependencies from wheels only (no build tools like gcc needed)
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

# Copy the application code into the image
COPY backend/ /app/

# Verify cache directories were copied (for debugging)
RUN echo "Checking cache directories..." && \
    ls -la /app/season_cache/ && \
    ls -la /app/tracks_cache/ && \
    echo "Season cache files: $(ls /app/season_cache/*.json 2>/dev/null | wc -l)" && \
    echo "Track cache files: $(ls /app/tracks_cache/*.json 2>/dev/null | wc -l)"

# Cache paths
# The season_cache and tracks_cache directories are bundled in the image
# with pre-generated JSON files for offline operation. Only the FastF1 cache
# (raw F1 telemetry data) is persisted as a volume between container runs.
# DO NOT declare season_cache or tracks_cache as volumes - it would overwrite
# the in-image cache files with empty directories.
ENV FASTF1_CACHE=/data/fastf1_cache
VOLUME ["/data/fastf1_cache"]

# Expose the FastAPI port
EXPOSE 8000

# Run the FastAPI application using Uvicorn
CMD ["uvicorn", "app.main:app", "--host=0.0.0.0", "--port=8000", "--access-log"]
