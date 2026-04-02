FROM python:3.11-slim

# System dependencies for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create runtime directories
RUN mkdir -p service_runs/image_archive service_runs/backups \
    service_runs/event_queue logs data

# Default environment
ENV ELITE_API_HOST=0.0.0.0
ENV ELITE_API_PORT=8877
ENV ELITE_LOG_LEVEL=info
ENV ELITE_OUTPUT_ROOT=/app/service_runs
ENV ELITE_HISTORY_DB=/app/data/quality_history.sqlite
ENV ELITE_INNOVATION_DB=/app/data/innovation_state.sqlite
ENV ELITE_AUDIT_LOG_PATH=/app/logs/elite_audit.jsonl
ENV ELITE_ALERT_DEAD_LETTER_PATH=/app/logs/elite_alert_dead_letter.jsonl

EXPOSE 8877

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8877/health')" || exit 1

CMD ["python", "-m", "uvicorn", "elite_api:app", "--host", "0.0.0.0", "--port", "8877"]
