FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --extra-index-url https://pypi.org/simple -r requirements.txt

COPY protos/ ./protos/
COPY scripts/ ./scripts/
COPY src/ ./src/

# Compile protobuf definitions
RUN python3 scripts/compile_protos.py

ENV PYTHONPATH=/app/src:/app/src/generated \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HEALTH_PORT=8081

EXPOSE 8080
EXPOSE 8081

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["python3", "-m", "src.main"]
