# A worker image owned by Data Platform, with no HTTP product API.
FROM python:3.11-slim@sha256:233de06753d30d120b1a3ce359d8d3be8bda78524cd8f520c99883bfe33964cf
WORKDIR /app
COPY etl-final/shared/cdc/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY etl-final/shared /app/shared
COPY bi_platform_shared /app/bi_platform_shared
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 1001:1001
ENTRYPOINT ["python", "-m", "shared.cdc.worker"]
