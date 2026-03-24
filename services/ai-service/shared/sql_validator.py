FORBIDDEN = ["DELETE", "DROP", "UPDATE", "INSERT", "ALTER"]


def validate_sql(sql: str):
    upper = sql.upper()
    for keyword in FORBIDDEN:
        if keyword in upper:
            raise ValueError("Forbidden SQL operation detected")