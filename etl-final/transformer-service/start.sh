#!/bin/bash

# Start Django server in the background
python transformer-service/transformer/manage.py runserver 0.0.0.0:8000 &

# Wait for Kafka to be ready
echo "[TRANSFORMER] Waiting for Kafka to be ready..."
sleep 30

# Start Kafka listener with retry logic
python -c "
import sys
import time
sys.path.insert(0, '/app/transformer-service/transformer')
sys.path.insert(0, '/app')

max_retries = 10
retry_count = 0

while retry_count < max_retries:
    try:
        print(f'[TRANSFORMER] Attempting to start listener (attempt {retry_count + 1}/{max_retries})...')
        from engine.kafka_listener import start_listener
        start_listener()
        break
    except Exception as e:
        print(f'[TRANSFORMER ERROR] Failed to connect: {e}')
        retry_count += 1
        if retry_count < max_retries:
            print(f'[TRANSFORMER] Retrying in 10 seconds...')
            time.sleep(10)
        else:
            print(f'[TRANSFORMER] Max retries reached. Exiting.')
            sys.exit(1)
"

