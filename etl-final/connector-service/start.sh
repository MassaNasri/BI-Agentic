#!/bin/bash
set -e

python -c "
from shared.kafka.topic_initializer import ensure_topics
ensure_topics()
"

exec python connector-service/connector/manage.py runserver 0.0.0.0:8000

