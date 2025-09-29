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

# Cache paths
# Only persist the FastF1 cache between container runs.  The season cache
# directory is left inside the image so that the bundled JSON files remain
# available at runtime.  Declaring it as a volume would overwrite the
# in-image data with an empty directory.
ENV FASTF1_CACHE=/data/fastf1_cache
VOLUME ["/data/fastf1_cache"]

# Expose the FastAPI port
EXPOSE 8000

# Run the FastAPI application using Uvicorn
CMD ["uvicorn", "app.main:app", "--host=0.0.0.0", "--port=8000", "--access-log"]
