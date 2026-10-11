#!/bin/sh
set -eu

clickhouse-client --user default --password "$CLICKHOUSE_PASSWORD" --multiquery <<'SQL'
CREATE DATABASE IF NOT EXISTS p1r_source;
CREATE TABLE p1r_source.customers (
 id Int64, customer_name String, email Nullable(String), active Bool, joined_date Date,
 created_at DateTime64(3,'UTC'), balance Decimal(30,10), profile_json Nullable(String)
) ENGINE=MergeTree ORDER BY id;
INSERT INTO p1r_source.customers VALUES
 (1,'Damascus – مرحبا',NULL,true,'2024-01-01','2024-01-01 07:00:00',12.3400000000,'{"city":"دمشق"}'),
 (2,'東京','tokyo@example.test',true,'2024-01-02','2024-01-01 23:30:00',999999999999.9900000000,'{"lang":"ja"}'),
 (3,'Zoë','zoe@example.test',false,'2024-01-03','2024-01-03 12:00:00',0.0100000000,NULL),
 (4,'Renée 😊',NULL,true,'2024-01-04','2024-01-04 12:00:00',-42.5000000000,'{"emoji":"😊"}'),
 (5,'Customer 5','c5@example.test',true,'2024-01-05','2024-01-05 12:00:00',5.0000000000,'{}'),
 (6,'Customer 6','c6@example.test',true,'2024-01-06','2024-01-06 12:00:00',6.0000000000,'{}'),
 (7,'Customer 7','c7@example.test',true,'2024-01-07','2024-01-07 12:00:00',7.0000000000,'{}'),
 (8,'Customer 8','c8@example.test',true,'2024-01-08','2024-01-08 12:00:00',8.0000000000,'{}');
CREATE TABLE p1r_source.empty_table (id Int64, note Nullable(String)) ENGINE=MergeTree ORDER BY id;
CREATE TABLE p1r_source.large_events (id Int64, payload String, occurred_at DateTime) ENGINE=MergeTree ORDER BY id;
INSERT INTO p1r_source.large_events SELECT number+1,concat('event-',toString(number+1)),toDateTime('2024-02-01 00:00:00')+number FROM numbers(2500);
CREATE TABLE p1r_source.`Sales Data` (`Order ID` Int64, `Total Value` Decimal(20,4), `select` Nullable(String)) ENGINE=MergeTree ORDER BY `Order ID`;
INSERT INTO p1r_source.`Sales Data` VALUES (1,10.2500,'alpha'),(2,20.5000,NULL),(3,30.7500,'مرحبا'),(4,40.0000,'東京');
SQL

clickhouse-client --user default --password "$CLICKHOUSE_PASSWORD" --multiquery <<SQL
CREATE USER IF NOT EXISTS biavora_reader IDENTIFIED WITH sha256_password BY '${P1R_READER_PASSWORD}' SETTINGS readonly=1;
GRANT SELECT ON p1r_source.* TO biavora_reader;
SQL
