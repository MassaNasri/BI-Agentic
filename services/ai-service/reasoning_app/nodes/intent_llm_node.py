from reasoning_app.llm_intent_client import classify_question
from reasoning_app.states import QueryState


def intent_llm_node(state: QueryState) -> QueryState:
    try:
        result = classify_question(state["text"])

        state["needs_sql"] = result.get("needs_sql", False)
        state["needs_chart"] = result.get("needs_chart", False)
        state["question_type"] = result.get("question_type", "informational")
        state["error"] = None

        return state

    except Exception as e:
        state["needs_sql"] = False
        state["needs_chart"] = False
        state["question_type"] = "error"
        state["error"] = str(e)

        return state
