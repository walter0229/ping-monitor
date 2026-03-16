# Dockerfile for Ping & Traceroute Monitor

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    iputils-ping \
    traceroute \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose port
EXPOSE 8000

# Set environment variables
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

# Command to run the application
# We use uvicorn directly instead of calling python app.py to avoid potential path issues
CMD uvicorn app:app --host 0.0.0.0 --port $PORT
