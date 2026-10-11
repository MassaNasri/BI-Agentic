#!/bin/sh
set -eu

psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=reader_password="$P1R_READER_PASSWORD" <<'SQL'
CREATE ROLE biavora_reader LOGIN PASSWORD :'reader_password';
CREATE SCHEMA company_data;
CREATE SCHEMA analytics_demo;
CREATE TABLE company_data.customers (
  id BIGINT PRIMARY KEY, external_id UUID NOT NULL, customer_name VARCHAR(120) NOT NULL,
  email TEXT NULL, active BOOLEAN NOT NULL, joined_date DATE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL, balance NUMERIC(30,10) NOT NULL, profile_json JSONB NULL
);
INSERT INTO company_data.customers VALUES
  (1,'00000000-0000-4000-8000-000000000001','Damascus – مرحبا',NULL,TRUE,'2024-01-01','2024-01-01T10:00:00+03:00',12.3400000000,'{"city":"دمشق"}'),
  (2,'00000000-0000-4000-8000-000000000002','東京','tokyo@example.test',TRUE,'2024-01-02','2024-01-02T08:30:00+09:00',999999999999.9900000000,'{"lang":"ja"}'),
  (3,'00000000-0000-4000-8000-000000000003','Zoë','zoe@example.test',FALSE,'2024-01-03','2024-01-03T12:00:00Z',0.0100000000,NULL),
  (4,'00000000-0000-4000-8000-000000000004','Renée 😊',NULL,TRUE,'2024-01-04','2024-01-04T12:00:00Z',-42.5000000000,'{"emoji":"😊"}'),
  (5,'00000000-0000-4000-8000-000000000005','Customer 5','c5@example.test',TRUE,'2024-01-05','2024-01-05T12:00:00Z',5.0000000000,'{}'),
  (6,'00000000-0000-4000-8000-000000000006','Customer 6','c6@example.test',TRUE,'2024-01-06','2024-01-06T12:00:00Z',6.0000000000,'{}'),
  (7,'00000000-0000-4000-8000-000000000007','Customer 7','c7@example.test',TRUE,'2024-01-07','2024-01-07T12:00:00Z',7.0000000000,'{}'),
  (8,'00000000-0000-4000-8000-000000000008','Customer 8','c8@example.test',TRUE,'2024-01-08','2024-01-08T12:00:00Z',8.0000000000,'{}');
CREATE TABLE company_data.empty_table (id BIGINT PRIMARY KEY, note TEXT NULL);
CREATE TABLE company_data.large_events (id BIGINT PRIMARY KEY, payload TEXT NOT NULL, occurred_at TIMESTAMPTZ NOT NULL);
INSERT INTO company_data.large_events
SELECT value, 'event-' || value, '2024-02-01T00:00:00Z'::timestamptz + value * interval '1 second'
FROM generate_series(1,2500) AS value;
CREATE TABLE analytics_demo."Sales Data" ("Order ID" BIGINT PRIMARY KEY, "Total Value" NUMERIC(20,4), "select" TEXT NULL);
INSERT INTO analytics_demo."Sales Data" VALUES (1,10.2500,'alpha'),(2,20.5000,NULL),(3,30.7500,'مرحبا'),(4,40.0000,'東京');
GRANT CONNECT ON DATABASE p1r_source TO biavora_reader;
GRANT USAGE ON SCHEMA company_data, analytics_demo TO biavora_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA company_data, analytics_demo TO biavora_reader;
SQL
