# Build from project root:  docker build -f deploy/Dockerfile -t booking-nlp .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY deploy/requirements-cloud.txt .
RUN pip install -r requirements-cloud.txt
COPY . .

ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 0 cloud_worker:app"]
