FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY app ./app

# Prepare persistent data directory
RUN mkdir -p /data

# Default environment variables
ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8080 \
    GATEWAY_ENABLED=true \
    GATEWAY_HOST=0.0.0.0 \
    GATEWAY_PORT=8081

# Expose Web Dashboard/API (8080) and Rotating Proxy Gateway (8081)
EXPOSE 8080 8081

# Run FastAPI with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
