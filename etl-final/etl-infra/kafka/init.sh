#!/bin/bash
set -e

BOOTSTRAP_SERVER="${KAFKA_BOOTSTRAP_SERVERS:-kafka:9092}"

TOPICS=(
  raw_data
  transformed_data
  load_requests
  metadata_updates
  errors
  quarantine
  connection_topic
  schema_topic
  extracted_rows_topic
  clean_rows_topic
  load_rows_topic
  metadata_topic
  extracted_rows_dlq
  clean_rows_dlq
  load_rows_dlq
)

for topic in "${TOPICS[@]}"; do
  kafka-topics --create --if-not-exists \
    --topic "${topic}" \
    --bootstrap-server "${BOOTSTRAP_SERVER}"
done
