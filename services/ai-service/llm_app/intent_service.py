import logging
from typing import Any

from llm_app.llm_client import call_llm
from llm_app.prompt_builder import build_prompt
from llm_app.response_parser import safe_json_parse
from llm_app.schema_provider import get_schema, is_question_matching_schema
from shared.error_response import make_error

logger = logging.getLogger(__name__)


def extract_intent(question: str) -> dict[str, Any]:
    try:
        schema = get_schema()
    except Exception as exc:
        return make_error(
            "clickhouse_connection_error",
            f"Failed to load schema metadata: {exc}",
            stage="schema",
            retryable=True,
        )

    matches_schema = is_question_matching_schema(question, schema)
    prompt = build_prompt(question, schema)

    try:
        raw_output = call_llm(prompt)
        intent = safe_json_parse(raw_output)
    except ValueError as exc:
        message = str(exc)
        error_code = "intent_parsing_error"
        if "openrouter" in message.lower() or "api_key" in message.lower():
            error_code = "llm_configuration_error"
        return make_error(
            error_code,
            message,
            stage="intent_extraction",
            retryable=False,
        )
    except RuntimeError as exc:
        message = str(exc)
        code = "llm_service_error"
        retryable = True
        if "rate limit" in message.lower():
            code = "llm_rate_limit"
        return make_error(
            code,
            message,
            stage="intent_extraction",
            retryable=retryable,
        )
    except Exception as exc:
        return make_error(
            "intent_parsing_error",
            f"Failed to parse LLM intent output: {exc}",
            stage="intent_extraction",
            retryable=False,
        )

    logger.info("Intent extracted successfully")
    return {
        "error": False,
        "intent": intent,
        "schema": schema,
        "matches_schema": matches_schema,
    }
