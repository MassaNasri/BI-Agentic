from pydantic import BaseModel
from typing import List, Optional


class Metric(BaseModel):
    column: str
    aggregation: str
    alias: Optional[str]


class Filter(BaseModel):
    column: str
    operator: str
    value: str


class Intent(BaseModel):
    table: str
    metrics: List[Metric]
    dimensions: List[str] = []
    filters: List[Filter] = []
    order_by: List[dict] = []
    limit: Optional[int] = None
