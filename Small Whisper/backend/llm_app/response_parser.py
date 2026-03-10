import json
import re


def _extract_json_blob(text: str) -> str:
    if not text or not text.strip():
        raise ValueError("Empty LLM response")

    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
    if fenced:
        return fenced.group(1)

    inline = re.search(r"\{[\s\S]*\}", text)
    if inline:
        return inline.group(0)

    raise ValueError("No JSON object found in LLM output")


def safe_json_parse(text: str) -> dict:
    blob = _extract_json_blob(text)
    try:
        return json.loads(blob)
    except json.JSONDecodeError as exc:
        cleaned = re.sub(r",\s*([}\]])", r"\1", blob)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON in LLM output: {exc.msg}") from exc
