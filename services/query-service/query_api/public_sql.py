"""Show authorized source table names without returning ClickHouse bindings."""

from sqlglot import exp, parse_one


def display_sql(sql, source_tables, *, fallback_table=None, dataset_id=None):
    mapping = {}
    for item in source_tables or []:
        if not isinstance(item, dict):
            continue
        destination = str(item.get("destination_table") or "").strip()
        name = str(item.get("name") or "").strip()
        schema = str(item.get("schema") or "").strip()
        if destination and name:
            mapping[destination.lower()] = (schema, name)
    if fallback_table and str(fallback_table).lower() not in mapping:
        mapping[str(fallback_table).lower()] = ("", f"dataset_{dataset_id}")
    if not mapping:
        return ""
    try:
        tree = parse_one(sql, read="clickhouse")
        if tree is None:
            return ""
        for table in tree.find_all(exp.Table):
            logical = mapping.get(table.name.lower())
            if logical is None:
                continue
            schema, name = logical
            table.set("this", exp.to_identifier(name))
            table.set("db", exp.to_identifier(schema) if schema else None)
            table.set("catalog", None)
        for column in tree.find_all(exp.Column):
            logical = mapping.get(column.table.lower()) if column.table else None
            if logical is None:
                continue
            schema, name = logical
            column.set("table", exp.to_identifier(name))
            column.set("db", exp.to_identifier(schema) if schema else None)
            column.set("catalog", None)
        public = tree.sql(dialect="clickhouse")
    except Exception:
        return ""
    if any(destination in public.lower() for destination in mapping):
        return ""
    return public


def public_query_payload(payload, *, workspace_id, dataset_id):
    if not isinstance(payload, dict) or not isinstance(payload.get("sql"), str):
        return payload
    result = dict(payload)
    try:
        from database.models import Database

        database = Database.objects.filter(pk=dataset_id, workspace_id=workspace_id).first()
        if database is None:
            result["sql"] = ""
        else:
            result["sql"] = display_sql(
                result["sql"], database.source_tables,
                fallback_table=database.clickhouse_table_name,
                dataset_id=database.pk,
            )
    except Exception:
        result["sql"] = ""
    return result
