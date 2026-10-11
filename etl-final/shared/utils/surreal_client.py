import os
import json
import os
import requests

class SurrealClient:

    def __init__(self):
        self.url = os.getenv("SURREAL_URL", "http://surrealdb:8000/sql")
        self.user = os.getenv("SURREAL_USER", "").strip()
        self.password = os.getenv("SURREAL_PASS", "")
        if not self.user or not self.password:
            raise RuntimeError("SURREAL_USER and SURREAL_PASS are required")
        self.ns = os.getenv("SURREAL_NS", "bi_etl")
        self.db = os.getenv("SURREAL_DB", "etl_logs")

    def query(self, sql: str):
        try:
            response = requests.post(
                self.url,
                auth=(self.user, self.password),
                headers={
                    "Content-Type": "text/plain",
                    "Accept": "application/json",
                    "surreal-ns": self.ns,
                    "surreal-db": self.db,
                },
                # Namespace/database are request context, not extra SQL
                # statements. Keeping the request to one statement also keeps
                # result[0] aligned with the query for existing serializers.
                data=sql,
                timeout=10
            )
            return response.json()
        except Exception:
            print("[SurrealDB ERROR] metadata request failed")
            return None

    def insert(self, table: str, record: dict):
        sql = f"CREATE {table} CONTENT {json.dumps(record)};"
        return self.query(sql)
