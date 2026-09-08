FROM python:3.12-slim

WORKDIR /app

# Install build dependencies for pip packages if necessary
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source and protos
COPY protos/ ./protos/
COPY compile_protos.py .
COPY src/ ./src/

# Compile the protos inside the image
RUN python3 compile_protos.py

# Configure dynamic runtime environment variables
ENV PYTHONPATH=/app/src:/app/src/generated \
    PYTHONUNBUFFERED=1 \
    PORT=8080

EXPOSE 8080

# Run as non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Start the gRPC server
ENTRYPOINT ["python3", "src/server.py"]
