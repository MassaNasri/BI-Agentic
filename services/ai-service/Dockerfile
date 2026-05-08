FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=600
ENV PIP_RETRIES=20
ENV PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --progress-bar off --upgrade pip "setuptools<81" wheel
# Install a stable CPU-only torch build (2.10.0+cpu is currently failing with invalid wheel/hash mismatch).
RUN pip install --no-cache-dir --progress-bar off \
    --index-url https://download.pytorch.org/whl/cpu \
    "torch==2.9.0+cpu"
RUN pip install --no-cache-dir --progress-bar off -r /app/requirements.txt

COPY . /app

EXPOSE 8005

CMD ["sh", "-c", "python manage.py runserver 0.0.0.0:8005"]

