from typing import TypedDict, Optional


class QueryState(TypedDict):
    text: str

    # Decision only
    needs_sql: bool
    needs_chart: bool
    question_type: str  # analytical | informational | error

    error: Optional[str]
