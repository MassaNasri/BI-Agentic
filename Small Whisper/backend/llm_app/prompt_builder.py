def build_prompt(question: str, schema: dict) -> str:
    schema_lines = []
    for table, columns in schema.items():
        schema_lines.append(f"Table: {table}")
        for col in columns:
            flags = []
            if col.get("is_numeric"):
                flags.append("numeric")
            if col.get("is_dimension"):
                flags.append("dimension")
            if col.get("is_date"):
                flags.append("date")
            flags_text = f" [{', '.join(flags)}]" if flags else ""
            schema_lines.append(f"  - {col['name']} ({col['type']}){flags_text}")

    schema_text = "\n".join(schema_lines)

    return f"""
You are an intent extraction model for analytical BI questions.

Output JSON only. Do not generate SQL. Do not include explanations.

Return the best candidate intent using ONLY schema fields.
The deterministic planner will finalize aggregation and ranking rules after you.
Your output should be semantically rich but conservative.

Analytical semantics to respect:
- If question asks average/mean -> use AVG.
- If question asks count/how many -> use COUNT.
- If question asks total/sum -> use SUM.
- If question asks most/highest/largest/top -> choose metric + dimension and include descending order hint.
- If question asks lowest/smallest/least/bottom -> choose metric + dimension and include ascending order hint.
- If ranking is implied and no number is provided, set limit to 1.
- Metrics should prefer numeric columns.
- Dimensions should prefer categorical/date columns.

Schema:
{schema_text}

Output format:
{{
  "table": "table_name",
  "metrics": [
    {{
      "column": "column_name_or_*",
      "aggregation": "SUM|COUNT|AVG|MIN|MAX",
      "alias": "optional_alias"
    }}
  ],
  "dimensions": ["dimension_column"],
  "filters": [
    {{
      "column": "column_name",
      "operator": "=|!=|>|<|>=|<=|IN|LIKE",
      "value": "value"
    }}
  ],
  "order_by": [
    {{
      "column": "metric_or_dimension",
      "direction": "ASC|DESC"
    }}
  ],
  "limit": 1
}}

Question:
{question}
""".strip()
