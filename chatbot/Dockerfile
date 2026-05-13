FROM python:3.11-slim

# Install system dependencies. curl is required by the HEALTHCHECK below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/data /app/logs /app/uploads /app/flask_session

# Set permissions
RUN chmod -R 755 /app

# Expose port
EXPOSE 8888

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8888/health || exit 1

# Run the application via waitress (production WSGI server)
CMD ["waitress-serve", "--port=8888", "--host=0.0.0.0", "app:app"]