# Home Inventory Management - Dockerfile
# Minimal Python container for local-first inventory tracking

FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create data directory for SQLite database
RUN mkdir -p /data

# Set environment variables
ENV DATABASE_PATH=/data/inventory.db
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 4269

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:4269/api/health')" || exit 1

# Run the application
# Host 0.0.0.0 allows access from local network
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4269"]

