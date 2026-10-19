FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/voice-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --default-timeout=600 --retries 25 --progress-bar off --upgrade pip "setuptools<81" wheel && pip install --no-cache-dir --default-timeout=600 --retries 25 --progress-bar off -r /app/requirements.txt

COPY bi_platform_shared /app/bi_platform_shared
COPY services/voice-service/ /app/

EXPOSE 8004

CMD ["sh", "-c", "(while true; do python -m bi_platform_shared.audio_cleanup voice; sleep 3600; done) & exec python manage.py runserver 0.0.0.0:8004"]

