import os
import threading
from queue import Queue, Empty
import pymysql
import psycopg2
from psycopg2.pool import SimpleConnectionPool

from shared.utils.db_type_utils import normalize_db_type


class _PooledConnection:
    def __init__(self, conn, release_fn):
        self._conn = conn
        self._release_fn = release_fn

    def close(self):
        self._release_fn(self._conn)

    def __getattr__(self, item):
        return getattr(self._conn, item)


class DBConnector:
    def __init__(self):
        self._pool_enabled = os.getenv("DB_POOL_ENABLED", "true").lower() in ("1", "true", "yes")
        self._pool_min = int(os.getenv("DB_POOL_MIN", "1"))
        self._pool_max = int(os.getenv("DB_POOL_MAX", "5"))
        self._mysql_pools = {}
        self._postgres_pools = {}
        self._lock = threading.Lock()

    def _pool_key(self, cfg):
        return f"{cfg['db_type']}:{cfg['host']}:{cfg['port']}:{cfg['database']}:{cfg['user']}"

    def _init_mysql_pool(self, cfg):
        key = self._pool_key(cfg)
        if key in self._mysql_pools:
            return
        with self._lock:
            if key in self._mysql_pools:
                return
            pool = Queue(maxsize=self._pool_max)
            for _ in range(self._pool_min):
                pool.put(self._create_mysql_connection(cfg))
            self._mysql_pools[key] = pool

    def _init_postgres_pool(self, cfg):
        key = self._pool_key(cfg)
        if key in self._postgres_pools:
            return
        with self._lock:
            if key in self._postgres_pools:
                return
            pool = SimpleConnectionPool(
                self._pool_min,
                self._pool_max,
                host=cfg["host"],
                user=cfg["user"],
                password=cfg["password"],
                dbname=cfg["database"],
                port=int(cfg["port"]),
            )
            self._postgres_pools[key] = pool

    def _create_mysql_connection(self, cfg):
        return pymysql.connect(
            host=cfg["host"],
            user=cfg["user"],
            password=cfg["password"],
            database=cfg["database"],
            port=int(cfg["port"]),
            cursorclass=pymysql.cursors.DictCursor
        )

    def connect_mysql(self, cfg):
        if not self._pool_enabled:
            return self._create_mysql_connection(cfg)

        self._init_mysql_pool(cfg)
        key = self._pool_key(cfg)
        pool = self._mysql_pools[key]
        try:
            conn = pool.get_nowait()
        except Empty:
            conn = self._create_mysql_connection(cfg)

        return _PooledConnection(conn, lambda c: pool.put(c) if not pool.full() else c.close())

    def connect_postgres(self, cfg):
        if not self._pool_enabled:
            return psycopg2.connect(
                host=cfg["host"],
                user=cfg["user"],
                password=cfg["password"],
                dbname=cfg["database"],
                port=int(cfg["port"])
            )

        self._init_postgres_pool(cfg)
        key = self._pool_key(cfg)
        pool = self._postgres_pools[key]
        conn = pool.getconn()
        return _PooledConnection(conn, lambda c: pool.putconn(c))

    def connect(self, cfg):
        db_type = normalize_db_type(cfg.get("db_type"))
        if db_type is None:
            raise Exception("Unsupported database type")
        cfg = {**cfg, "db_type": db_type}
        if db_type == "mysql":
            return self.connect_mysql(cfg)
        elif db_type == "postgres":
            return self.connect_postgres(cfg)
        else:
            raise Exception("Unsupported database type")
