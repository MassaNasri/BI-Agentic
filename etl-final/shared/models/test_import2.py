import sys
import traceback

try:
    # Try importing transformation_rule first
    from transformation_rule import (
        TransformationRule,
        TransformationResult,
        RuleExecutionContext,
        RuleExecutionRecord,
        RuleType
    )
    print("transformation_rule imports successful")
    
    # Now try importing rules_engine
    exec(open('rules_engine.py').read())
    print("rules_engine executed successfully")
    
except Exception as e:
    print(f"Error: {e}")
    traceback.print_exc()
