"""
Demonstration of Rule Priority and Ordering in RulesEngine

This script demonstrates how the RulesEngine applies transformation rules
in priority order, ensuring deterministic and predictable transformations.

**Validates: Requirements US-6 (AC 6.2) - Deterministic cleaning rules with explicit rule execution order**
"""
from transformation_rule import TransformationRule, RuleType
from rules_engine import RulesEngine


def demo_basic_priority_ordering():
    """Demonstrate basic priority ordering."""
    print("=" * 70)
    print("DEMO 1: Basic Priority Ordering")
    print("=" * 70)
    
    # Create rules with different priorities
    rules = [
        TransformationRule(
            rule_id="add_suffix",
            rule_type=RuleType.TRANSFORM,
            priority=10,  # Runs third
            condition=lambda row: True,
            action=lambda row: {**row, "name": row["name"] + "_FINAL"},
            metadata={"description": "Add final suffix"}
        ),
        TransformationRule(
            rule_id="trim_whitespace",
            rule_type=RuleType.CLEAN,
            priority=1,  # Runs first
            condition=lambda row: True,
            action=lambda row: {k: v.strip() if isinstance(v, str) else v 
                               for k, v in row.items()},
            metadata={"description": "Trim whitespace from strings"}
        ),
        TransformationRule(
            rule_id="uppercase_name",
            rule_type=RuleType.TRANSFORM,
            priority=5,  # Runs second
            condition=lambda row: "name" in row,
            action=lambda row: {**row, "name": row["name"].upper()},
            metadata={"description": "Convert name to uppercase"}
        )
    ]
    
    # Input data
    row = {"name": "  john doe  ", "age": 30}
    
    print(f"\nInput row: {row}")
    print("\nRules (in input order):")
    for rule in rules:
        print(f"  - {rule.rule_id} (priority={rule.priority}): {rule.metadata.get('description')}")
    
    # Apply rules
    result = RulesEngine.apply_rules(row, rules)
    
    print("\nExecution order (by priority):")
    for i, rule_id in enumerate(result.applied_rules, 1):
        rule = next(r for r in rules if r.rule_id == rule_id)
        print(f"  {i}. {rule_id} (priority={rule.priority})")
    
    print(f"\nFinal result: {result.transformed_row}")
    print(f"Quality score: {result.quality_score}")


def demo_priority_independence():
    """Demonstrate that priority determines order regardless of input list order."""
    print("\n" + "=" * 70)
    print("DEMO 2: Priority Independence from Input Order")
    print("=" * 70)
    
    # Create rules in reverse priority order
    rules_reversed = [
        TransformationRule(
            rule_id="step_3",
            rule_type=RuleType.TRANSFORM,
            priority=3,
            condition=lambda row: True,
            action=lambda row: {**row, "sequence": row.get("sequence", "") + "C"}
        ),
        TransformationRule(
            rule_id="step_2",
            rule_type=RuleType.TRANSFORM,
            priority=2,
            condition=lambda row: True,
            action=lambda row: {**row, "sequence": row.get("sequence", "") + "B"}
        ),
        TransformationRule(
            rule_id="step_1",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: True,
            action=lambda row: {**row, "sequence": row.get("sequence", "") + "A"}
        )
    ]
    
    # Create same rules in forward priority order
    rules_forward = [
        TransformationRule(
            rule_id="step_1",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: True,
            action=lambda row: {**row, "sequence": row.get("sequence", "") + "A"}
        ),
        TransformationRule(
            rule_id="step_2",
            rule_type=RuleType.TRANSFORM,
            priority=2,
            condition=lambda row: True,
            action=lambda row: {**row, "sequence": row.get("sequence", "") + "B"}
        ),
        TransformationRule(
            rule_id="step_3",
            rule_type=RuleType.TRANSFORM,
            priority=3,
            condition=lambda row: True,
            action=lambda row: {**row, "sequence": row.get("sequence", "") + "C"}
        )
    ]
    
    row = {"sequence": ""}
    
    result_reversed = RulesEngine.apply_rules(row, rules_reversed)
    result_forward = RulesEngine.apply_rules(row, rules_forward)
    
    print("\nInput list order: REVERSED (3, 2, 1)")
    print(f"Result: {result_reversed.transformed_row['sequence']}")
    print(f"Execution order: {result_reversed.applied_rules}")
    
    print("\nInput list order: FORWARD (1, 2, 3)")
    print(f"Result: {result_forward.transformed_row['sequence']}")
    print(f"Execution order: {result_forward.applied_rules}")
    
    print("\n✓ Both produce identical results - priority determines order!")


def demo_priority_guidelines():
    """Demonstrate recommended priority guidelines."""
    print("\n" + "=" * 70)
    print("DEMO 3: Priority Guidelines in Practice")
    print("=" * 70)
    
    rules = [
        # Priority 0-10: Critical cleaning
        TransformationRule(
            rule_id="remove_nulls",
            rule_type=RuleType.CLEAN,
            priority=1,
            condition=lambda row: True,
            action=lambda row: {k: v for k, v in row.items() if v is not None},
            metadata={"category": "Critical Cleaning"}
        ),
        TransformationRule(
            rule_id="trim_strings",
            rule_type=RuleType.CLEAN,
            priority=2,
            condition=lambda row: True,
            action=lambda row: {k: v.strip() if isinstance(v, str) else v 
                               for k, v in row.items()},
            metadata={"category": "Critical Cleaning"}
        ),
        
        # Priority 11-50: Standard transformations
        TransformationRule(
            rule_id="parse_date",
            rule_type=RuleType.TRANSFORM,
            priority=20,
            condition=lambda row: "date_str" in row,
            action=lambda row: {**row, "parsed_date": f"PARSED({row['date_str']})"},
            metadata={"category": "Standard Transformation"}
        ),
        TransformationRule(
            rule_id="normalize_email",
            rule_type=RuleType.TRANSFORM,
            priority=25,
            condition=lambda row: "email" in row,
            action=lambda row: {**row, "email": row["email"].lower()},
            metadata={"category": "Standard Transformation"}
        ),
        
        # Priority 51-100: Enrichment
        TransformationRule(
            rule_id="add_full_name",
            rule_type=RuleType.ENRICH,
            priority=60,
            condition=lambda row: "first_name" in row and "last_name" in row,
            action=lambda row: {**row, "full_name": f"{row['first_name']} {row['last_name']}"},
            metadata={"category": "Enrichment"}
        ),
        
        # Priority 101+: Validation
        TransformationRule(
            rule_id="validate_email",
            rule_type=RuleType.VALIDATE,
            priority=110,
            condition=lambda row: "email" in row,
            action=lambda row: {**row, "email_valid": "@" in row["email"]},
            metadata={"category": "Validation"}
        )
    ]
    
    row = {
        "first_name": "  John  ",
        "last_name": "  Doe  ",
        "email": "  JOHN.DOE@EXAMPLE.COM  ",
        "date_str": "2024-01-15",
        "null_field": None
    }
    
    print(f"\nInput row: {row}")
    print("\nRule execution by priority category:")
    
    result = RulesEngine.apply_rules(row, rules)
    
    current_category = None
    for rule_id in result.applied_rules:
        rule = next(r for r in rules if r.rule_id == rule_id)
        category = rule.metadata.get("category")
        if category != current_category:
            print(f"\n{category}:")
            current_category = category
        print(f"  - {rule_id} (priority={rule.priority})")
    
    print(f"\nFinal result:")
    for key, value in result.transformed_row.items():
        print(f"  {key}: {value}")
    
    print(f"\nQuality score: {result.quality_score}")


def demo_conditional_priority():
    """Demonstrate priority with conditional rules."""
    print("\n" + "=" * 70)
    print("DEMO 4: Priority with Conditional Rules")
    print("=" * 70)
    
    rules = [
        TransformationRule(
            rule_id="default_status",
            rule_type=RuleType.TRANSFORM,
            priority=1,
            condition=lambda row: True,
            action=lambda row: {**row, "status": "pending"},
            metadata={"description": "Set default status"}
        ),
        TransformationRule(
            rule_id="vip_status",
            rule_type=RuleType.TRANSFORM,
            priority=10,
            condition=lambda row: row.get("is_vip", False),
            action=lambda row: {**row, "status": "priority"},
            metadata={"description": "Override status for VIP customers"}
        ),
        TransformationRule(
            rule_id="urgent_status",
            rule_type=RuleType.TRANSFORM,
            priority=20,
            condition=lambda row: row.get("is_urgent", False),
            action=lambda row: {**row, "status": "urgent"},
            metadata={"description": "Override status for urgent cases"}
        )
    ]
    
    # Test case 1: Regular customer
    row1 = {"customer_id": 1, "is_vip": False, "is_urgent": False}
    result1 = RulesEngine.apply_rules(row1, rules)
    print(f"\nRegular customer: {row1}")
    print(f"Applied rules: {result1.applied_rules}")
    print(f"Final status: {result1.transformed_row['status']}")
    
    # Test case 2: VIP customer
    row2 = {"customer_id": 2, "is_vip": True, "is_urgent": False}
    result2 = RulesEngine.apply_rules(row2, rules)
    print(f"\nVIP customer: {row2}")
    print(f"Applied rules: {result2.applied_rules}")
    print(f"Final status: {result2.transformed_row['status']}")
    
    # Test case 3: Urgent case (highest priority)
    row3 = {"customer_id": 3, "is_vip": True, "is_urgent": True}
    result3 = RulesEngine.apply_rules(row3, rules)
    print(f"\nUrgent VIP customer: {row3}")
    print(f"Applied rules: {result3.applied_rules}")
    print(f"Final status: {result3.transformed_row['status']}")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("TRANSFORMATION RULES ENGINE - PRIORITY ORDERING DEMONSTRATION")
    print("=" * 70)
    print("\nThis demo shows how the RulesEngine applies rules in priority order")
    print("to ensure deterministic, predictable transformations.")
    print("\nKey Principle: LOWER priority numbers execute FIRST")
    
    demo_basic_priority_ordering()
    demo_priority_independence()
    demo_priority_guidelines()
    demo_conditional_priority()
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("""
Priority Ordering Rules:
1. Lower priority numbers execute first (0 < 1 < 2 < ...)
2. Priority determines order regardless of input list order
3. Rules with same priority maintain their list order (stable sort)
4. Each rule sees the output of all previous rules
5. Priority must be non-negative (0 or greater)

Recommended Priority Ranges:
- 0-10:    Critical cleaning (trim, remove nulls, fix encoding)
- 11-50:   Standard transformations (type conversions, formatting)
- 51-100:  Enrichment (add derived fields, lookups)
- 101+:    Final validation and quality checks

This ensures consistent, documented rule execution order as required
by US-6 (AC 6.2).
    """)
