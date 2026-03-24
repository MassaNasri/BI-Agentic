def normalize_intent(intent: dict, schema: dict) -> dict:
    table = intent["table"]

    if table not in schema:
        raise ValueError("Invalid table selected by LLM")

    valid_columns = schema[table]

    # metric
    if intent.get("metric"):
        m = intent["metric"].lower()
        if m in ["number", "count", "total"]:
            intent["metric"] = "count"

    # columns
    if intent.get("columns"):
        intent["columns"] = [
            c for c in intent["columns"] if c in valid_columns
        ]

    # group_by
    if intent.get("group_by") not in valid_columns:
        intent["group_by"] = None

    # filters
    cleaned_filters = []
    for f in intent.get("filters") or []:
        if f["column"] in valid_columns:
            cleaned_filters.append(f)
    intent["filters"] = cleaned_filters

    return intent
