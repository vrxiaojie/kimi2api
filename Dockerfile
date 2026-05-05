FROM hub.rat.dev/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    KIMI2API_CONFIG=/data/config.json

WORKDIR /app

RUN mkdir -p /data

COPY requirements.txt ./

RUN pip install --no-cache-dir --retries 10 -r requirements.txt

COPY app ./app
COPY webui ./webui
COPY run.py ./
COPY setup.py ./
COPY README.md ./
COPY LICENSE ./
COPY config.example.json ./

EXPOSE 8080

VOLUME ["/data"]

CMD ["python", "run.py", "serve", "--host", "0.0.0.0", "--port", "8080"]