from reasoning_app.graph import build_graph
from reasoning_app.states import QueryState

graph = build_graph()


def run_reasoning(text: str) -> QueryState:
    initial_state: QueryState = {
        "text": text,
        "needs_sql": False,
        "needs_chart": False,
        "question_type": "",
        "error": None,
    }

    return graph.invoke(initial_state)
