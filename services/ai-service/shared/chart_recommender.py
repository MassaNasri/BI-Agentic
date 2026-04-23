import logging


logger = logging.getLogger(__name__)


def _single_value_shape(data: dict | None) -> bool:
    if not isinstance(data, dict):
        return False
    rows = data.get("rows", [])
    if not isinstance(rows, list) or len(rows) != 1:
        return False
    first = rows[0]
    return isinstance(first, dict) and len(first.keys()) == 1


def _metric_alias(metric: object, fallback: str) -> str:
    if isinstance(metric, dict):
        alias = str(metric.get("alias") or "").strip()
        if alias:
            return alias
    return fallback


def _is_numeric_like(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return False
        if stripped.startswith("-"):
            stripped = stripped[1:]
        return stripped.replace(".", "", 1).isdigit()
    return False


def _shape_profile(data: dict | None) -> dict:
    if not isinstance(data, dict):
        return {"columns": [], "numeric_columns": [], "time_like_columns": [], "row_count": 0}

    rows = data.get("rows", [])
    columns = data.get("columns", [])
    if not isinstance(rows, list):
        rows = []
    if not isinstance(columns, list):
        columns = []

    column_names: list[str] = []
    for column in columns:
        if isinstance(column, dict):
            name = str(column.get("name") or "").strip()
        else:
            name = str(column or "").strip()
        if name:
            column_names.append(name)

    sample_rows = [row for row in rows if isinstance(row, dict)][:25]
    numeric_columns: list[str] = []
    time_like_columns: list[str] = []
    for column_name in column_names:
        lowered = column_name.lower()
        if any(token in lowered for token in ("date", "time", "period", "day", "week", "month", "quarter", "year")):
            time_like_columns.append(column_name)
        observed = [row.get(column_name) for row in sample_rows if column_name in row and row.get(column_name) is not None]
        if observed and all(_is_numeric_like(value) for value in observed):
            numeric_columns.append(column_name)

    return {
        "columns": column_names,
        "numeric_columns": numeric_columns,
        "time_like_columns": time_like_columns,
        "row_count": len(rows),
    }


def recommend_chart(intent: dict, data: dict | None = None) -> dict:
    """
    Recommend a chart type based on analytical intent and result shape.
    Priority: correlation -> time_series -> distribution -> category comparison -> card.
    """

    metrics = intent.get("metrics", []) if isinstance(intent.get("metrics"), list) else []
    dimensions = intent.get("dimensions", []) if isinstance(intent.get("dimensions"), list) else []
    limit = intent.get("limit")
    intent_type = str(intent.get("intent_type", "")).strip().lower()
    primary_intent = str(intent.get("intent", "")).strip().lower()
    operations = {
        str(op).strip().lower()
        for op in (intent.get("operations", []) or [])
        if str(op).strip()
    }
    analysis_mode = str(intent.get("analysis_mode", "")).strip().lower()
    time_grouping_detected = bool(intent.get("time_grouping_detected"))
    time_granularity = str(intent.get("time_granularity", "")).strip().lower()

    num_metrics = len(metrics)
    num_dimensions = len(dimensions)

    if intent_type == "predictive":
        return {
            "type": "line",
            "mode": "actual_plus_predicted",
            "series_type_field": "series_type",
            "series_label_field": "series_label",
            "preferred_color_role_field": "preferred_color_role",
            "chart_series_config": [
                {
                    "series_type": "actual",
                    "series_label": "Actual",
                    "preferred_color_role": "actual",
                    "preferred_color": "#2563eb",
                    "stroke_dasharray": "",
                },
                {
                    "series_type": "forecast",
                    "series_label": "Forecast",
                    "preferred_color_role": "forecast",
                    "preferred_color": "#f97316",
                    "stroke_dasharray": "6 4",
                },
            ],
        }

    shape = _shape_profile(data)
    numeric_columns = shape.get("numeric_columns", [])
    time_like_columns = shape.get("time_like_columns", [])
    row_count = int(shape.get("row_count", 0) or 0)
    all_columns = shape.get("columns", [])
    has_category_value_shape = bool(
        row_count >= 1
        and len(numeric_columns) >= 1
        and len(all_columns) > len(numeric_columns)
    )

    relationship_requested = (
        analysis_mode == "relationship"
        or primary_intent in {"correlation", "relationship"}
        or "relationship" in operations
    )
    time_series_requested = (
        time_grouping_detected
        or time_granularity in {"hour", "day", "week", "month", "quarter", "year"}
        or primary_intent == "time_series"
        or "time_grouping" in operations
    )
    distribution_requested = (
        analysis_mode == "distribution"
        or primary_intent == "distribution"
        or "distribution" in operations
    )

    # 1) Correlation -> scatter
    if relationship_requested and (num_metrics >= 2 or len(numeric_columns) >= 2):
        x_axis = _metric_alias(metrics[0], numeric_columns[0] if len(numeric_columns) >= 1 else "x") if num_metrics >= 1 else (
            numeric_columns[0] if len(numeric_columns) >= 1 else "x"
        )
        y_axis = _metric_alias(metrics[1], numeric_columns[1] if len(numeric_columns) >= 2 else "y") if num_metrics >= 2 else (
            numeric_columns[1] if len(numeric_columns) >= 2 else "y"
        )
        return {
            "type": "scatter",
            "x": x_axis,
            "y": y_axis,
        }

    # 2) Time series -> line
    if time_series_requested and (
        (num_metrics >= 1 and num_dimensions >= 1)
        or (len(time_like_columns) >= 1 and len(numeric_columns) >= 1)
    ):
        x_axis = (
            str(dimensions[0]).strip()
            if num_dimensions >= 1 and str(dimensions[0]).strip()
            else (time_like_columns[0] if time_like_columns else "period")
        )
        y_axis = _metric_alias(metrics[0], numeric_columns[0] if numeric_columns else "value")
        if num_metrics < 1:
            y_axis = numeric_columns[0] if numeric_columns else "value"
        return {
            "type": "line",
            "x": x_axis,
            "y": y_axis,
        }

    # 3) Distribution -> histogram
    if distribution_requested and (num_metrics >= 1 or len(numeric_columns) == 1):
        metric_axis = _metric_alias(metrics[0], numeric_columns[0] if numeric_columns else "value") if num_metrics >= 1 else (
            numeric_columns[0] if numeric_columns else "value"
        )
        return {
            "type": "histogram",
            "x": metric_axis,
        }

    # 4) Category comparison -> bar
    if num_metrics == 1 and num_dimensions >= 1:
        return {
            "type": "bar",
            "x": dimensions[0],
            "y": _metric_alias(metrics[0], "value"),
            "sorted": True if limit else False,
        }

    # 5) Single value -> card
    if _single_value_shape(data) or (num_metrics == 1 and num_dimensions == 0 and data is None):
        return {
            "type": "card",
            "metric": _metric_alias(metrics[0], "value") if num_metrics == 1 else "value",
        }

    # Shape rules (validated fallback, no blind table override)
    if row_count >= 1 and len(time_like_columns) >= 1 and len(numeric_columns) >= 1:
        return {
            "type": "line",
            "x": time_like_columns[0],
            "y": numeric_columns[0],
        }
    if row_count > 1 and len(numeric_columns) >= 2 and not has_category_value_shape:
        return {
            "type": "scatter",
            "x": numeric_columns[0],
            "y": numeric_columns[1],
        }
    if row_count > 1 and len(numeric_columns) == 1 and not has_category_value_shape:
        return {
            "type": "histogram",
            "x": numeric_columns[0],
        }
    if has_category_value_shape:
        category = next((col for col in all_columns if col not in numeric_columns), "category")
        return {
            "type": "bar",
            "x": category,
            "y": numeric_columns[0] if numeric_columns else "value",
        }
    if _single_value_shape(data):
        return {
            "type": "card",
            "metric": "value",
        }

    return {
        "type": "table"
    }
