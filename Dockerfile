FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .
COPY monitor.py .
COPY healthcheck.py .
COPY diagnose.py .

# Create data directory
RUN mkdir -p /data

# Healthy = latest_forecast.json was rewritten recently (see healthcheck.py)
HEALTHCHECK --interval=5m --timeout=10s --start-period=2m --retries=2 \
  CMD ["python", "healthcheck.py"]

# Run the application
CMD ["python", "-u", "app.py"]
