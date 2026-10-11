"""
Property-based tests for deterministic transformer behavior.
"""
import random

from shared.models.transformation_rule import TransformationRule, RuleType
from shared.models.rules_engine import RulesEngine
from shared.models.rule_actions import trim_strings, uppercase_strings
from shared.models.rule_conditions import always_true
from .transformer_service import TransformerService


def _random_row(rng: random.Random) -> dict:
    return {
        "name": rng.choice(["  alice  ", "Bob", "  CHARLIE  "]),
        "age": rng.choice([str(rng.randint(0, 100)), rng.randint(0, 100)]),
        "active": rng.choice(["yes", "no", True, False]),
        "city": rng.choice(["New York", "  Los Angeles  ", "Chicago"]),
    }


def _build_rules():
    return [
        TransformationRule(
            rule_id="trim_strings_v1",
            rule_type=RuleType.CLEAN,
            priority=1,
            condition=always_true,
            action=trim_strings,
        ),
        TransformationRule(
            rule_id="uppercase_strings_v1",
            rule_type=RuleType.TRANSFORM,
            priority=2,
            condition=always_true,
            action=uppercase_strings,
        ),
    ]


def test_rules_engine_determinism_randomized():
    rng = random.Random(1337)
    rules = _build_rules()

    for _ in range(50):
        row = _random_row(rng)
        result1 = RulesEngine.apply_rules(row, rules)
        result2 = RulesEngine.apply_rules(row, rules)
        assert result1.transformed_row == result2.transformed_row
        assert result1.applied_rules == result2.applied_rules


def test_transformer_service_determinism_randomized():
    rng = random.Random(2026)
    rules = _build_rules()
    service = TransformerService(default_rules=rules, drop_invalid=False)

    messages = []
    for i in range(50):
        messages.append({
            "source": "test_source",
            "batch_id": f"batch_{i}",
            "data": _random_row(rng),
        })

    results1, stats1 = service.process_batch(messages)
    results2, stats2 = service.process_batch(messages)

    def stable_message(result):
        message = dict(result["clean_message"])
        message.pop("_cleaned_at", None)
        message.pop("cleaned_at", None)
        return message

    assert [stable_message(r) for r in results1] == [stable_message(r) for r in results2]
    assert all(r["clean_message"].get("_cleaned_at") for r in results1 + results2)
    assert stats1["success"] == stats2["success"]
