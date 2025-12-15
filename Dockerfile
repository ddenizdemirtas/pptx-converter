# PPTX Converter Service
# Multi-stage build for smaller final image

# =============================================================================
# Stage 1: Python dependencies
# =============================================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt

# =============================================================================
# Stage 2: Final image
# =============================================================================
FROM python:3.12-slim

# Labels
LABEL org.opencontainers.image.title="PPTX Converter Service"
LABEL org.opencontainers.image.description="Converts PPTX files to PDF using LibreOffice"

# Create non-root user for security
RUN groupadd --gid 1000 converter && \
    useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home converter

WORKDIR /app

# Install LibreOffice and fonts
# Using libreoffice-impress specifically for PPTX support
RUN apt-get update && apt-get install -y --no-install-recommends \
    # LibreOffice core and Impress for presentations
    libreoffice-core \
    libreoffice-impress \
    libreoffice-writer \
    # Fonts - basic set for document rendering
    fonts-liberation \
    fonts-dejavu-core \
    fonts-freefont-ttf \
    fonts-noto-core \
    fonts-noto-cjk \
    fontconfig \
    # Required for headless operation
    libxinerama1 \
    libgl1 \
    # Clean up
    && rm -rf /var/lib/apt/lists/* \
    # Update font cache
    && fc-cache -fv

# Copy Python wheels and install
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy application code
COPY app/ /app/app/

# Create temp directory with correct permissions
RUN mkdir -p /tmp/converter && chown -R converter:converter /tmp/converter

# Switch to non-root user
USER converter

# Environment defaults
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    CONCURRENCY=1 \
    CONVERSION_TIMEOUT_SECONDS=180 \
    MAX_INPUT_SIZE_MB=100 \
    TEMP_DIR=/tmp/converter \
    LOG_LEVEL=INFO

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Run the service
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

