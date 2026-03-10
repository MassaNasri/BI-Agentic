import logging


logger = logging.getLogger(__name__)


def recommend_chart(intent: dict, data: dict | None = None) -> dict:
    """
    Recommend a chart type based on the analytical intent.
    This function is question-agnostic and dataset-agnostic.
    """

    metrics = intent.get("metrics", [])
    dimensions = intent.get("dimensions", [])
    limit = intent.get("limit")

    num_metrics = len(metrics)
    num_dimensions = len(dimensions)

    # ---- KPI ----
    if num_metrics == 1 and num_dimensions == 0:
        return {
            "type": "kpi",
            "metric": metrics[0]["alias"]
        }

    # ---- Line Chart (time dimension heuristic) ----
    if num_metrics == 1 and num_dimensions == 1:
        dim = dimensions[0].lower()
        if any(t in dim for t in ["date", "time", "year", "month"]):
            return {
                "type": "line",
                "x": dimensions[0],
                "y": metrics[0]["alias"]
            }

    # ---- Bar Chart ----
    if num_metrics == 1 and num_dimensions == 1:
        return {
            "type": "bar",
            "x": dimensions[0],
            "y": metrics[0]["alias"],
            "sorted": True if limit else False
        }

    # ---- Grouped Bar ----
    if num_metrics > 1 and num_dimensions == 1:
        logger.info("Chart recommendation mapped: grouped_bar -> bar")
        return {
            "type": "bar",
            "x": dimensions[0],
            "ys": [m["alias"] for m in metrics]
        }

    # ---- Fallback ----
    return {
        "type": "table"
    }
