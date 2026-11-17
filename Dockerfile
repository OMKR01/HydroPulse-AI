# HydroPulse AI — Multi-Stage Hardened Production Dockerfile
# Stage 1: Dependency Builder
FROM python:3.11-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install build dependencies for compiling binary wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies to isolated prefix
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# -------------------------------------------------------------
# Stage 2: Minimal Non-Root Production Runner
FROM python:3.11-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/install/bin:${PATH}" \
    PYTHONPATH="/app:/install/lib/python3.11/site-packages:${PYTHONPATH}" \
    FLASK_APP=src.hydropulse.api.factory:create_app \
    PORT=5000 \
    HOST=0.0.0.0

# Install only minimal runtime dependencies (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed python dependencies from builder
COPY --from=builder /install /install

# Create unprivileged system group and user (UID/GID 1000)
RUN groupadd -g 1000 hydropulse && \
    useradd -u 1000 -g hydropulse -s /bin/bash -m hydropulse

# Copy application configuration, source, and metadata
COPY --chown=hydropulse:hydropulse config/ config/
COPY --chown=hydropulse:hydropulse data/ data/
COPY --chown=hydropulse:hydropulse reports/ reports/
COPY --chown=hydropulse:hydropulse src/ src/
COPY --chown=hydropulse:hydropulse pyproject.toml README.md .env.example ./

# Ensure write permissions for database and report outputs
RUN mkdir -p data/interim reports/runs reports/plots && \
    chown -R hydropulse:hydropulse /app

# Switch to unprivileged user
USER hydropulse

EXPOSE 5000

# Container healthcheck targeting standard REST API health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/v1/health || exit 1

# Default execution: Gunicorn WSGI production server
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "60", "src.hydropulse.api.factory:create_app()"]
