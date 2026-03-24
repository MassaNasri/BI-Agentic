from langgraph.graph import StateGraph, END
from reasoning_app.states import QueryState
from reasoning_app.nodes.intent_llm_node import intent_llm_node
from reasoning_app.nodes.routing_node import routing_node


def build_graph():
    graph = StateGraph(QueryState)

    graph.add_node("intent_llm", intent_llm_node)
    graph.set_entry_point("intent_llm")

    graph.add_conditional_edges(
        "intent_llm",
        routing_node,
        {
            "analytical": END,
            "non_analytical": END,
            "error": END,
        }
    )

    return graph.compile()
