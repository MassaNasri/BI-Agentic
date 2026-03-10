FROM python:3.10-slim

WORKDIR /app

COPY metadata-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY metadata-service /app/metadata-service
COPY shared /app/shared

ENV PYTHONPATH="/app"

EXPOSE 8000

# Copy and set execute permission for startup script
COPY metadata-service/start.sh /app/start.sh
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

CMD ["/app/start.sh"]
