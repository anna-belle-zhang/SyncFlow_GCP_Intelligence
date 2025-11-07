FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY *.py ./
COPY app/ ./app/
COPY agents/ ./agents/

# Create non-root user
RUN useradd -m -u 1000 syncflow && chown -R syncflow:syncflow /app
USER syncflow

# Health check
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose port (Cloud Run uses 8080)
EXPOSE 8080

# Run application on Cloud Run's standard port
CMD ["python", "syncflow_server.py", "--host", "0.0.0.0", "--port", "8080"]
