FROM python:3.11-slim

# Install system-level OpenCV dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY *.py ./
COPY *.json ./
COPY web_assets/ ./web_assets/

# Runtime directories
RUN mkdir -p /data/service_runs /data/logs

ENV ELITE_API_HOST=0.0.0.0
ENV ELITE_API_PORT=8877
ENV ELITE_OUTPUT_ROOT=/data/service_runs
ENV ELITE_HISTORY_DB=/data/quality_history.sqlite
ENV ELITE_INNOVATION_DB=/data/innovation_state.sqlite
ENV ELITE_AUDIT_LOG_PATH=/data/logs/elite_audit.jsonl
ENV ELITE_ALERT_DEAD_LETTER_PATH=/data/logs/elite_alert_dead_letter.jsonl

EXPOSE 8877

VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8877/health')" || exit 1

CMD ["python", "-m", "uvicorn", "elite_api:app", \
     "--host", "0.0.0.0", \
     "--port", "8877", \
     "--workers", "1", \
     "--log-level", "info"]
