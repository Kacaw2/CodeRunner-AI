# Dockerfile for Flask Application
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies including GCC and development tools
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    build-essential \
    default-mysql-client \
    curl \
    procps \
    gosu \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Verify GCC installation
RUN gcc --version && python3 --version

# Create app user (security best practice)
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app /tmp/executor && \
    chown -R appuser:appuser /app /tmp/executor

# Set work directory
WORKDIR /app

# Copy requirements first (better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Pre-bundle the embedding (+ rerank) models into the image so the container
# never downloads from HuggingFace at runtime (F6). Models land in /opt/models.
ENV HF_HOME=/opt/models \
    SENTENCE_TRANSFORMERS_HOME=/opt/models \
    TRANSFORMERS_CACHE=/opt/models
COPY scripts/prefetch_models.py /tmp/prefetch_models.py
RUN python /tmp/prefetch_models.py && rm /tmp/prefetch_models.py && \
    chown -R appuser:appuser /opt/models
# Force fully-offline model loading at runtime: a missing model fails loudly
# instead of silently reaching out to the network.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# Copy application code
COPY --chown=appuser:appuser . .

# Copy and set up entrypoint script (if exists)
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create necessary directories
RUN mkdir -p /app/instance /app/logs /app/uploads && \
    chown -R appuser:appuser /app /tmp/executor

# Expose port
EXPOSE 9900

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:9900/health || exit 1

# Use entrypoint to handle initialization
ENTRYPOINT ["/app/entrypoint.sh"]

# Run application with gunicorn
CMD ["gosu", "appuser", "gunicorn", "--bind", "0.0.0.0:9900", "--workers", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "run:app"]
