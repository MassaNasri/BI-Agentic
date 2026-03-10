#!/bin/bash

# Start Django server in background
python detector-service/detector/manage.py runserver 0.0.0.0:8000 &

echo "[DETECTOR] Waiting for Kafka to be ready..."
sleep 30

python -c "
import sys
import time

sys.path.insert(0, '/app/detector-service/detector')
sys.path.insert(0, '/app')

max_retries = 15
retry_count = 0

while retry_count < max_retries:
    try:
        print(f'[DETECTOR] Attempting to start listener (attempt {retry_count+1}/{max_retries})')
        from core.kafka_listener import start_listener
        start_listener()
        break
    except Exception as e:
        print(f'[DETECTOR ERROR] Kafka not ready: {e}')
        retry_count += 1
        time.sleep(10)

print('[DETECTOR] Listener stopped')
"
