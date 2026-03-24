from shared.pipeline import process_question


def generate_sql_and_chart(question: str) -> dict:
    result = process_question(question)
    if result.get("error"):
        return {"type": "error", "message": result.get("message"), "details": result}

    return {
        "sql": result["sql"],
        "chart": result["chart"],
        "intent": result["intent"],
    }
