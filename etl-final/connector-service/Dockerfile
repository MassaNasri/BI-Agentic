FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY etl-final/connector-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --default-timeout=600 --retries 25 --progress-bar off --upgrade pip "setuptools<81" wheel && pip install --no-cache-dir --default-timeout=600 --retries 25 --progress-bar off -r /app/requirements.txt

# Copy service source
COPY etl-final/connector-service /app/connector-service

# Copy shared utils/models
COPY etl-final/shared /app/shared
COPY bi_platform_shared /app/bi_platform_shared

ENV PYTHONPATH="/app"

EXPOSE 8000

COPY etl-final/connector-service/start.sh /app/start.sh
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

CMD ["/app/start.sh"]

