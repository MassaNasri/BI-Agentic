from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

def _resolve_repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in (current.parent, *current.parents):
        if (candidate / "bi_platform_shared").is_dir():
            return candidate
    raise RuntimeError("Could not locate repository root containing bi_platform_shared")


REPO_ROOT = _resolve_repo_root()
SERVICE_ROOT = REPO_ROOT / "services" / "visualization-service"
if not SERVICE_ROOT.is_dir():
    SERVICE_ROOT = REPO_ROOT
for path in (REPO_ROOT, SERVICE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from bi_platform_shared.contracts.chart import (  # noqa: E402
    ChartTypeEnum,
    chart_shape_support_failure,
    is_chart_shape_supported,
    recommend_chart_types,
)
from visualization_api.services import chart_type_selector as cts  # noqa: E402


def test_time_series_recommendation_has_primary_and_ranked_alternatives():
    result = recommend_chart_types(
        shape={
            "type": "time_series",
            "row_count": 12,
            "time_field": "period",
            "metric_fields": ["sum_sales"],
        }
    )
    payload = result.model_dump(mode="json")

    assert payload["recommended"]["chart_type"] == "line"
    assert payload["recommended_chart_type"] == "line"
    assert payload["chart_type"] == "line"
    assert payload["recommended"]["chart_type"] not in {
        item["chart_type"] for item in payload["alternatives"]
    }
    assert len(payload["alternatives"]) <= 3
    assert payload["alternatives"] == sorted(
        payload["alternatives"],
        key=lambda item: item["confidence"],
        reverse=True,
    )


def test_small_category_result_prefers_bar_with_pie_available():
    result = recommend_chart_types(
        shape={
            "type": "grouped",
            "row_count": 3,
            "category_fields": ["category"],
            "metric_fields": ["revenue"],
            "cardinality": {"category": 3},
        }
    ).model_dump(mode="json")

    assert result["recommended"]["chart_type"] == "bar"
    assert "pie" in {item["chart_type"] for item in result["alternatives"]}


def test_large_category_result_marks_pie_incompatible():
    result = recommend_chart_types(
        shape={
            "type": "grouped",
            "row_count": 24,
            "category_fields": ["product"],
            "metric_fields": ["revenue"],
            "cardinality": {"product": 24},
        }
    ).model_dump(mode="json")

    pie = [item for item in result["incompatible"] if item["chart_type"] == "pie"]
    assert pie
    assert pie[0]["reason_code"] == "too_many_categories"


def test_two_numeric_metrics_prefers_scatter_and_single_metric_rejects_scatter():
    scatter = recommend_chart_types(
        shape={
            "type": "multi_metric",
            "row_count": 10,
            "metric_fields": ["revenue", "profit"],
        }
    ).model_dump(mode="json")

    assert scatter["recommended"]["chart_type"] == "scatter"
    assert not is_chart_shape_supported(
        ChartTypeEnum.SCATTER,
        {"type": "single_value", "row_count": 1, "metric_fields": ["revenue"]},
    )


def test_single_aggregate_prefers_card_and_no_time_field_rejects_line():
    card = recommend_chart_types(
        shape={
            "type": "single_value",
            "row_count": 1,
            "metric_fields": ["average_order_value"],
        }
    ).model_dump(mode="json")

    assert card["recommended"]["chart_type"] == "card"
    code, reason = chart_shape_support_failure(
        ChartTypeEnum.LINE,
        {"type": "grouped", "row_count": 3, "category_fields": ["city"], "metric_fields": ["sales"]},
    )
    assert code == "requires_time_dimension"
    assert "time" in reason.lower()


@patch.object(cts, "requests")
def test_ollama_prompt_receives_only_compatible_chart_types(mock_requests):
    captured_prompt = {}

    def _post(url, json, timeout):  # noqa: ARG001
        captured_prompt["text"] = json["prompt"]

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"response": '{"chart_type":"bar","reason":"compatible"}'}

        return _Response()

    mock_requests.post.side_effect = _post
    out = cts.select_chart_type_with_ollama(
        name="Sales by city",
        sql="SELECT city, SUM(sales) AS sales FROM t GROUP BY city",
        requested_chart_type="",
        visualization_settings={
            "dataset_columns": [{"name": "city", "type": "String"}, {"name": "sales", "type": "Float64"}],
            "result_rows": [{"city": "Damascus", "sales": 10.0}, {"city": "Aleppo", "sales": 12.0}],
        },
        ai_trace={"original_question": {"text": "Sales by city"}},
    )

    allowed_line = captured_prompt["text"].split("Allowed chart_type values only:", 1)[1].split("\n", 1)[0]
    assert out["chart_type"] == "bar"
    assert "bar" in allowed_line
    assert "scatter" not in allowed_line
