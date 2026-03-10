import logging

from llm_app.intent_service import extract_intent
from reasoning_app.runner import run_reasoning
from shared.chart_recommender import recommend_chart
from shared.error_response import make_error
from shared.query_planner import normalize_analytical_intent
from shared.sql_compiler import compile_sql
from shared.sql_validator import validate_sql

logger = logging.getLogger(__name__)


def process_question(question: str) -> dict:
    extraction_result = extract_intent(question)
    if extraction_result.get("error"):
        return extraction_result

    raw_intent = extraction_result["intent"]
    schema = extraction_result["schema"]

    try:
        intent = normalize_analytical_intent(
            question=question,
            raw_intent=raw_intent,
            schema=schema,
        )
    except ValueError as exc:
        return make_error(
            "intent_normalization_error",
            str(exc),
            stage="query_planner",
            details={"raw_intent": raw_intent},
            retryable=False,
        )
    except Exception as exc:
        return make_error(
            "query_planner_error",
            f"Unexpected planner failure: {exc}",
            stage="query_planner",
            details={"raw_intent": raw_intent},
            retryable=False,
        )

    try:
        sql = compile_sql(intent, schema=schema)
        validate_sql(sql)
    except ValueError as exc:
        return make_error(
            "invalid_sql",
            str(exc),
            stage="sql_generation",
            details={"intent": intent},
            retryable=False,
        )
    except Exception as exc:
        return make_error(
            "sql_generation_error",
            f"Unexpected SQL generation failure: {exc}",
            stage="sql_generation",
            details={"intent": intent},
            retryable=False,
        )

    chart = recommend_chart(intent)
    confidence = _calculate_confidence(intent, schema, extraction_result.get("matches_schema", False))

    return {
        "error": False,
        "intent": intent,
        "sql": sql,
        "chart": chart,
        "confidence": confidence,
        "raw_intent": raw_intent,
    }


def _columns_from_intent(intent: dict) -> list[str]:
    columns = set()
    for metric in intent.get("metrics", []):
        col = metric.get("column")
        if col:
            columns.add(col)
    for dim in intent.get("dimensions", []):
        columns.add(dim)
    for flt in intent.get("filters", []):
        col = flt.get("column")
        if col:
            columns.add(col)
    for order in intent.get("order_by", []):
        col = order.get("column")
        if col:
            columns.add(col)
    return sorted(columns)


def _calculate_confidence(intent: dict, schema: dict, matches_schema: bool) -> float:
    confidence = 0.65 if matches_schema else 0.45
    table = intent.get("table")
    if table in schema:
        confidence += 0.15
    if intent.get("metrics"):
        confidence += 0.1
    if intent.get("order_by"):
        confidence += 0.05
    if intent.get("dimensions"):
        confidence += 0.05
    return max(0.0, min(1.0, confidence))


def process_after_whisper(text: str):
    state = run_reasoning(text)

    reasoning = {
        "question_type": state.get("question_type"),
        "needs_sql": state.get("needs_sql", False),
        "needs_chart": state.get("needs_chart", False),
    }

    if not reasoning["needs_sql"] or reasoning["question_type"] != "analytical":
        reasoning["message"] = "The question does not require data analysis. SQL generation was skipped."
        return reasoning, None

    stage_result = process_question(text)
    if stage_result.get("error"):
        reasoning["message"] = stage_result.get("message")
        reasoning["analytical_error"] = stage_result
        return reasoning, None

    intent = stage_result["intent"]
    llm = {
        "intent": intent,
        "sql": stage_result["sql"],
        "chart": stage_result["chart"],
        "confidence": stage_result.get("confidence", 0.5),
        "columns": _columns_from_intent(intent),
    }
    return reasoning, llm
