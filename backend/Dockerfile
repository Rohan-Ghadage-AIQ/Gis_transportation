
# Use a slim version for smaller image size
FROM python:3.11-slim

# Install system dependencies required for OR-Tools, PostgreSQL, and GDAL (for geopandas)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Health check so docker-compose knows when backend is ready
HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]