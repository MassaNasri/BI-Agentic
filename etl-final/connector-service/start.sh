#!/bin/bash
set -e

python -c "
from shared.kafka.topic_initializer import ensure_topics
ensure_topics()
"

# The upload volume is private staging storage. Prune abandoned files even
# when no further uploads arrive; the loop exits with the container.
(
  while true; do
    python connector-service/cleanup_uploads.py
    sleep 3600
  done
) &

exec python connector-service/connector/manage.py runserver 0.0.0.0:8000

