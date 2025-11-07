FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Streamlit and dependencies
RUN pip install --no-cache-dir \
    streamlit>=1.28.0 \
    plotly>=5.17.0 \
    pandas>=2.0.0 \
    requests>=2.31.0

# Copy application code
COPY dashboard.py .

# Create non-root user
RUN useradd -m -u 1000 streamlit && chown -R streamlit:streamlit /app
USER streamlit

# Create .streamlit directory for configuration
RUN mkdir -p ~/.streamlit

# Cloud Run uses port 8080
EXPOSE 8080

# Run Streamlit on Cloud Run's port (8080)
CMD ["streamlit", "run", "dashboard.py", "--server.port=8080", "--server.address=0.0.0.0", "--client.showErrorDetails=false"]
