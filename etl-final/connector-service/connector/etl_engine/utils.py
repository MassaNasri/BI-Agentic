import psycopg2
import pymysql

from shared.utils.db_type_utils import normalize_db_type


def test_db_connection(db_type, host, user, password, database, port):
    """
    Tests a database connection for MySQL or PostgreSQL.
    """

    try:

        normalized_db_type = normalize_db_type(db_type)

        if normalized_db_type == "mysql":
            conn = pymysql.connect(
                host=host,
                user=user,
                password=password,
                database=database,
                port=int(port),
            )

        elif normalized_db_type == "postgres":
            conn = psycopg2.connect(
                host=host,
                user=user,
                password=password,
                dbname=database,
                port=int(port),
            )

        else:
            return False, "Unsupported database type"

        conn.close()
        return True, "Connection successful"

    except Exception as e:
        return False, str(e)
