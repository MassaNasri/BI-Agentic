"""
Test runner script for rate limiting tests.
Sets up Python path correctly for local testing.
"""

import os
import sys
import django

# Add parent directory of shared to path (so we can import shared.utils)
etl_final_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if etl_final_path not in sys.path:
    sys.path.insert(0, etl_final_path)

# Add connector service to path
connector_path = os.path.join(os.path.dirname(__file__), 'connector')
if connector_path not in sys.path:
    sys.path.insert(0, connector_path)

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'connector.settings')
django.setup()

# Run tests
if __name__ == '__main__':
    from django.core.management import execute_from_command_line
    
    # Run the rate limiting tests
    execute_from_command_line(['manage.py', 'test', 'etl_engine.test_rate_limiting', '-v', '2'])
