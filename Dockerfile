# Dockerfile for ProTraderHack backend
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PORT=5000

# Install build deps
RUN apt-get update && apt-get install -y build-essential gcc && rm -rf /var/lib/apt/lists/*

# Copy and install python deps
COPY requirements.txt .
RUN python -m pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy repo files
COPY . .

# Expose the port
EXPOSE ${PORT}

# Launch via gunicorn using PORT env var
CMD ["sh", "-c", "gunicorn main:app --bind 0.0.0.0:${PORT} --workers 3 --threads 2"]
