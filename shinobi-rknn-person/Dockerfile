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
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements-container.txt && \
    python -c "import cv2, numpy, socketio; print('OpenCV', cv2.__version__); print('NumPy', numpy.__version__)"

COPY plugin.py /app/plugin.py
COPY config.container.json /app/config.json

CMD ["python", "/app/plugin.py", "--config", "/app/config.json"]
