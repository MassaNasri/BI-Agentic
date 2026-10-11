#!/bin/sh
set -eu

sqlplus -s / as sysdba <<SQL
ALTER SESSION SET CONTAINER=FREEPDB1;
CREATE USER p1reader IDENTIFIED BY "$P1R_READER_PASSWORD";
GRANT CREATE SESSION TO p1reader;
GRANT SELECT ON p1user.customers TO p1reader;
GRANT SELECT ON p1user.empty_table TO p1reader;
GRANT SELECT ON p1user.large_events TO p1reader;
GRANT SELECT ON p1user."Sales Data" TO p1reader;
SQL
