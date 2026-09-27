FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-container.txt .
RUN pip install -r requirements-container.txt

COPY plugin.py /app/plugin.py
COPY config.container.json /app/config.json

CMD ["python", "/app/plugin.py", "--config", "/app/config.json"]
