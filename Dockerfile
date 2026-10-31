# HydroPulse AI — Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=src.hydropulse.api.factory:create_app \
    PORT=5000 \
    HOST=0.0.0.0

# Install system dependencies if required
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source and configs
COPY config/ config/
COPY data/ data/
COPY reports/ reports/
COPY src/ src/
COPY pyproject.toml README.md .env.example ./

# Install project in editable/package mode
RUN pip install --no-cache-dir -e .

EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/api/v1/health || exit 1

# Start gunicorn production WSGI server
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "src.hydropulse.api.factory:create_app()"]
