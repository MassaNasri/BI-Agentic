from reasoning_app.states import QueryState


def routing_node(state: QueryState) -> str:
    """
    Decide graph routing based on intent classification
    """
    if state.get("error"):
        return "error"

    if state.get("needs_sql"):
        return "analytical"

    return "non_analytical"
