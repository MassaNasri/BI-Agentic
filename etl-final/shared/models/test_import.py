import sys
import importlib

# Clear cached module
if 'rules_engine' in sys.modules:
    del sys.modules['rules_engine']

# Import the module
import rules_engine

print("Module contents:", dir(rules_engine))
print("Has RulesEngine:", hasattr(rules_engine, 'RulesEngine'))

if hasattr(rules_engine, 'RulesEngine'):
    print("RulesEngine imported successfully!")
else:
    print("RulesEngine NOT found in module")
    print("File location:", rules_engine.__file__)
