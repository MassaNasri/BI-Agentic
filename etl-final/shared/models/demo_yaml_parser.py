"""
Demo script for YAML Rule Parser
Demonstrates loading and using transformation rules from YAML files.
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
parent_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(parent_dir))

# Import with package imports
from shared.models.rule_yaml_parser import load_rules_from_yaml
from shared.models.rules_engine import RulesEngine

def main():
    print("=" * 60)
    print("YAML Rule Parser Demo")
    print("=" * 60)
    
    # Load rules from YAML file
    print("\n1. Loading rules from example_rules.yaml...")
    rules = load_rules_from_yaml("example_rules.yaml")
    print(f"   Loaded {len(rules)} rules")
    
    # Display loaded rules
    print("\n2. Loaded Rules:")
    for rule in sorted(rules, key=lambda r: r.priority):
        print(f"   - {rule.rule_id} ({rule.rule_type.name}, priority={rule.priority})")
        if "description" in rule.metadata:
            print(f"     Description: {rule.metadata['description']}")
    
    # Create rules engine
    print("\n3. Validating rules...")
    validation_errors = RulesEngine.validate_rules(rules)
    if validation_errors:
        print(f"   Validation errors: {validation_errors}")
        return
    print("   Rules validated successfully!")
    
    # Test data
    test_row = {
        "first_name": "  John  ",
        "last_name": "  Doe  ",
        "age": "30",
        "email": "  john.doe@example.com  ",
        "middle_name": None
    }
    
    print("\n4. Original Row:")
    for key, value in test_row.items():
        print(f"   {key}: {repr(value)}")
    
    # Apply rules
    print("\n5. Applying transformation rules...")
    result = RulesEngine.apply_rules(test_row, rules)
    
    print("\n6. Transformed Row:")
    for key, value in result.transformed_row.items():
        print(f"   {key}: {repr(value)}")
    
    print(f"\n7. Applied Rules: {result.applied_rules}")
    
    if result.warnings:
        print(f"\n8. Warnings: {result.warnings}")
    
    if result.errors:
        print(f"\n9. Errors: {result.errors}")
    
    print("\n" + "=" * 60)
    print("Demo completed successfully!")
    print("=" * 60)

if __name__ == "__main__":
    main()
