#!/bin/sh
set -eu

mysql --default-character-set=utf8mb4 -uroot -p"$MYSQL_ROOT_PASSWORD" -e "CREATE USER 'biavora_reader'@'%' IDENTIFIED BY '$P1R_READER_PASSWORD';"
mysql --default-character-set=utf8mb4 -uroot -p"$MYSQL_ROOT_PASSWORD" <<'SQL'
SET SESSION cte_max_recursion_depth=3000;
CREATE TABLE p1r_source.customers (
  id BIGINT PRIMARY KEY AUTO_INCREMENT, customer_name VARCHAR(120) NOT NULL, email TEXT NULL,
  active BOOLEAN NOT NULL, joined_date DATE NOT NULL, created_at DATETIME(6) NOT NULL,
  balance DECIMAL(30,10) NOT NULL, profile_json JSON NULL
) CHARACTER SET utf8mb4;
INSERT INTO p1r_source.customers VALUES
 (1,'Damascus – مرحبا',NULL,TRUE,'2024-01-01','2024-01-01 10:00:00',12.3400000000,JSON_OBJECT('city','دمشق')),
 (2,'東京','tokyo@example.test',TRUE,'2024-01-02','2024-01-02 08:30:00',999999999999.9900000000,JSON_OBJECT('lang','ja')),
 (3,'Zoë','zoe@example.test',FALSE,'2024-01-03','2024-01-03 12:00:00',0.0100000000,NULL),
 (4,'Renée 😊',NULL,TRUE,'2024-01-04','2024-01-04 12:00:00',-42.5000000000,JSON_OBJECT('emoji','😊')),
 (5,'Customer 5','c5@example.test',TRUE,'2024-01-05','2024-01-05 12:00:00',5.0000000000,JSON_OBJECT()),
 (6,'Customer 6','c6@example.test',TRUE,'2024-01-06','2024-01-06 12:00:00',6.0000000000,JSON_OBJECT()),
 (7,'Customer 7','c7@example.test',TRUE,'2024-01-07','2024-01-07 12:00:00',7.0000000000,JSON_OBJECT()),
 (8,'Customer 8','c8@example.test',TRUE,'2024-01-08','2024-01-08 12:00:00',8.0000000000,JSON_OBJECT());
CREATE TABLE p1r_source.empty_table (id BIGINT PRIMARY KEY, note TEXT NULL);
CREATE TABLE p1r_source.large_events (id BIGINT PRIMARY KEY, payload VARCHAR(80) NOT NULL, occurred_at DATETIME NOT NULL);
INSERT INTO p1r_source.large_events WITH RECURSIVE seq AS (SELECT 1 n UNION ALL SELECT n+1 FROM seq WHERE n<2500)
SELECT n,CONCAT('event-',n),DATE_ADD('2024-02-01 00:00:00',INTERVAL n SECOND) FROM seq;
CREATE TABLE p1r_source.`Sales Data` (`Order ID` BIGINT PRIMARY KEY, `Total Value` DECIMAL(20,4), `select` TEXT NULL) CHARACTER SET utf8mb4;
INSERT INTO p1r_source.`Sales Data` VALUES (1,10.2500,'alpha'),(2,20.5000,NULL),(3,30.7500,'مرحبا'),(4,40.0000,'東京');
SQL
mysql --default-character-set=utf8mb4 -uroot -p"$MYSQL_ROOT_PASSWORD" -e "GRANT SELECT ON p1r_source.* TO 'biavora_reader'@'%'; FLUSH PRIVILEGES;"
