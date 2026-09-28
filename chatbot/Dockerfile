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

# The data directory must belong to the runtime user: a fresh named volume
# mounted at /app/data takes over this ownership, and with root as owner the
# app could not create its database.
RUN mkdir -p /app/data && chmod -R 755 /app && chown -R 1000:1000 /app/data

USER 1000:1000

# Expose port
EXPOSE 8888

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8888/health || exit 1

# Run the application via waitress (production WSGI server)
CMD ["waitress-serve", "--port=8888", "--host=0.0.0.0", "app:app"]