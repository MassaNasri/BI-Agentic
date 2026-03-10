"""
Enhanced Kafka Message Schema Validator
Provides comprehensive schema validation for all Kafka topics with type checking and constraints.
"""
from typing import Dict, Any, Optional, List, Tuple, Union
from datetime import datetime
import re

from shared.config.kafka_topics import resolve_validation_topic


class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass


class FieldValidator:
    """Validates individual field values against type and constraint definitions."""
    
    VALID_TYPES = {
        'string', 'integer', 'float', 'boolean', 'datetime', 
        'dict', 'list', 'any'
    }
    
    @staticmethod
    def validate_type(value: Any, expected_type: str) -> Tuple[bool, Optional[str]]:
        """
        Validate that a value matches the expected type.
        
        Args:
            value: The value to validate
            expected_type: Expected type as string
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if expected_type not in FieldValidator.VALID_TYPES:
            return False, f"Unknown type: {expected_type}"
        
        if expected_type == 'any':
            return True, None
        
        type_checks = {
            'string': lambda v: isinstance(v, str),
            'integer': lambda v: isinstance(v, int) and not isinstance(v, bool),
            'float': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            'boolean': lambda v: isinstance(v, bool),
            'datetime': lambda v: isinstance(v, (str, datetime)),
            'dict': lambda v: isinstance(v, dict),
            'list': lambda v: isinstance(v, list),
        }
        
        if not type_checks[expected_type](value):
            return False, f"Expected {expected_type}, got {type(value).__name__}"
        
        return True, None
    
    @staticmethod
    def validate_constraints(value: Any, constraints: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate value against constraints.
        
        Supported constraints:
        - min: minimum value (for numbers)
        - max: maximum value (for numbers)
        - min_length: minimum string/list length
        - max_length: maximum string/list length
        - pattern: regex pattern (for strings)
        - enum: allowed values
        - not_empty: value cannot be empty string/list/dict
        
        Args:
            value: The value to validate
            constraints: Dictionary of constraints
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not constraints:
            return True, None
        
        # Min/max for numbers
        if 'min' in constraints:
            if isinstance(value, (int, float)) and value < constraints['min']:
                return False, f"Value {value} is less than minimum {constraints['min']}"
        
        if 'max' in constraints:
            if isinstance(value, (int, float)) and value > constraints['max']:
                return False, f"Value {value} exceeds maximum {constraints['max']}"
        
        # Length constraints
        if 'min_length' in constraints:
            if hasattr(value, '__len__') and len(value) < constraints['min_length']:
                return False, f"Length {len(value)} is less than minimum {constraints['min_length']}"
        
        if 'max_length' in constraints:
            if hasattr(value, '__len__') and len(value) > constraints['max_length']:
                return False, f"Length {len(value)} exceeds maximum {constraints['max_length']}"
        
        # Pattern matching for strings
        if 'pattern' in constraints and isinstance(value, str):
            if not re.match(constraints['pattern'], value):
                return False, f"Value does not match pattern {constraints['pattern']}"
        
        # Enum validation
        if 'enum' in constraints:
            if value not in constraints['enum']:
                return False, f"Value '{value}' not in allowed values: {constraints['enum']}"
        
        # Not empty validation
        if constraints.get('not_empty', False):
            if isinstance(value, (str, list, dict)) and len(value) == 0:
                return False, "Value cannot be empty"
        
        return True, None


class KafkaSchemaValidator:
    """
    Comprehensive schema validator for Kafka messages.
    Validates message structure, field types, and constraints.
    """
    
    # Schema definitions for each Kafka topic
    SCHEMAS = {
        'connection_topic': {
            'required_fields': ['type'],
            'fields': {
                'type': {
                    'type': 'string',
                    'constraints': {'enum': ['file', 'database']}
                },
                'filename': {
                    'type': 'string',
                    'required_if': {'type': 'file'},
                    'constraints': {'not_empty': True, 'max_length': 255}
                },
                'path': {
                    'type': 'string',
                    'required_if': {'type': 'file'},
                    'constraints': {'not_empty': True}
                },
                'size': {
                    'type': 'integer',
                    'required_if': {'type': 'file'},
                    'constraints': {'min': 0}
                },
                'db_type': {
                    'type': 'string',
                    'required_if': {'type': 'database'},
                    'constraints': {'enum': ['mysql', 'postgres', 'sqlite', 'mssql', 'oracle']}
                },
                'host': {
                    'type': 'string',
                    'required_if': {'type': 'database'},
                    'constraints': {'not_empty': True}
                },
                'user': {
                    'type': 'string',
                    'required_if': {'type': 'database'},
                    'constraints': {'not_empty': True}
                },
                'password': {
                    'type': 'string',
                    'required_if': {'type': 'database'}
                },
                'database': {
                    'type': 'string',
                    'required_if': {'type': 'database'},
                    'constraints': {'not_empty': True}
                },
                'port': {
                    'type': 'integer',
                    'required_if': {'type': 'database'},
                    'constraints': {'min': 1, 'max': 65535}
                }
            }
        },
        'schema_topic': {
            'required_fields': ['source', 'type', 'columns'],
            'fields': {
                'source': {
                    'type': 'string',
                    'constraints': {'not_empty': True}
                },
                'type': {
                    'type': 'string',
                    'constraints': {'enum': ['file', 'database']}
                },
                'columns': {
                    'type': 'list',
                    'constraints': {'not_empty': True}
                },
                'dtypes': {
                    'type': 'dict',
                    'required': False
                },
                'row_count': {
                    'type': 'integer',
                    'required': False,
                    'constraints': {'min': 0}
                },
                'table': {
                    'type': 'string',
                    'required': False
                }
            }
        },
        'extracted_rows_topic': {
            'required_fields': ['source', 'source_id', 'schema_version'],
            'fields': {
                'source': {
                    'type': 'string',
                    'constraints': {'not_empty': True}
                },
                'source_id': {
                    'type': 'string',
                    'constraints': {'not_empty': True}
                },
                'row_id': {
                    'type': 'integer',
                    'required': False,
                    'constraints': {'min': 0}
                },
                'table': {
                    'type': 'string',
                    'required': False
                },
                'data': {
                    'type': 'dict',
                    'required': False,
                    'constraints': {'not_empty': True}
                },
                'rows': {
                    'type': 'list',
                    'required': False,
                    'constraints': {'not_empty': True}
                },
                'batch_id': {
                    'type': 'string',
                    'required': False
                },
                'extracted_at': {
                    'type': 'string',
                    'required': False
                },
                'row_count': {
                    'type': 'integer',
                    'required': False,
                    'constraints': {'min': 1}
                },
                'schema_version': {
                    'type': 'string',
                    'required': True,
                    'constraints': {'not_empty': True}
                }
            }
        },
        'clean_rows_topic': {
            'required_fields': ['source', 'source_id', 'schema_version'],
            'fields': {
                'source': {
                    'type': 'string',
                    'constraints': {'not_empty': True}
                },
                'source_id': {
                    'type': 'string',
                    'constraints': {'not_empty': True}
                },
                'row_id': {
                    'type': 'integer',
                    'required': False
                },
                'table': {
                    'type': 'string',
                    'required': False
                },
                'data': {
                    'type': 'dict',
                    'required': False,
                    'constraints': {'not_empty': True}
                },
                'rows': {
                    'type': 'list',
                    'required': False,
                    'constraints': {'not_empty': True}
                },
                'batch_id': {
                    'type': 'string',
                    'required': False
                },
                'cleaned_at': {
                    'type': 'string',
                    'required': False
                },
                'row_count': {
                    'type': 'integer',
                    'required': False,
                    'constraints': {'min': 1}
                },
                'schema_version': {
                    'type': 'string',
                    'required': True,
                    'constraints': {'not_empty': True}
                },
                'quality_score': {
                    'type': 'float',
                    'required': False,
                    'constraints': {'min': 0.0, 'max': 1.0}
                },
                'warnings': {
                    'type': 'list',
                    'required': False
                }
            }
        },
        'load_rows_topic': {
            'required_fields': ['source', 'status'],
            'fields': {
                'source': {
                    'type': 'string',
                    'constraints': {'not_empty': True}
                },
                'table': {
                    'type': 'string',
                    'required': False
                },
                'status': {
                    'type': 'string',
                    'constraints': {'enum': ['success', 'error']}
                },
                'row_count': {
                    'type': 'integer',
                    'required': False,
                    'constraints': {'min': 0}
                },
                'error': {
                    'type': 'string',
                    'required_if': {'status': 'error'}
                },
                'batch_id': {
                    'type': 'string',
                    'required': False
                }
            }
        },
        'metadata_topic': {
            'required_fields': ['timestamp'],
            'fields': {
                'event_type': {
                    'type': 'string',
                    'constraints': {'not_empty': True}
                },
                'metadata_type': {
                    'type': 'string',
                    'required': False,
                    'constraints': {'not_empty': True}
                },
                'timestamp': {
                    'type': 'string',
                    'constraints': {'not_empty': True}
                },
                'source': {
                    'type': 'string',
                    'required': False
                },
                'data': {
                    'type': 'dict',
                    'required': False
                }
            }
        }
    }
    
    @classmethod
    def validate_message(cls, topic: str, message: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate a message against the schema for a specific topic.
        
        Args:
            topic: Kafka topic name
            message: Message dictionary to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        normalized_topic = resolve_validation_topic(topic)
        if normalized_topic not in cls.SCHEMAS:
            return True, None  # No schema defined, allow message
        
        schema = cls.SCHEMAS[normalized_topic]
        
        # Validate required fields
        for field in schema.get('required_fields', []):
            if field not in message:
                return False, f"Missing required field: {field}"
        
        # Validate conditional required fields
        for field_name, field_def in schema['fields'].items():
            if 'required_if' in field_def:
                condition = field_def['required_if']
                condition_field = list(condition.keys())[0]
                condition_value = condition[condition_field]
                
                if message.get(condition_field) == condition_value:
                    if field_name not in message:
                        return False, f"Missing required field '{field_name}' when {condition_field}={condition_value}"
        
        # Validate each field present in the message
        for field_name, field_value in message.items():
            if field_name not in schema['fields']:
                continue  # Allow extra fields
            
            field_def = schema['fields'][field_name]
            
            # Skip validation for None values unless explicitly required
            if field_value is None:
                if field_name in schema.get('required_fields', []):
                    return False, f"Required field '{field_name}' cannot be None"
                continue
            
            # Validate type
            expected_type = field_def.get('type', 'any')
            is_valid, error = FieldValidator.validate_type(field_value, expected_type)
            if not is_valid:
                return False, f"Field '{field_name}': {error}"
            
            # Validate constraints
            constraints = field_def.get('constraints', {})
            is_valid, error = FieldValidator.validate_constraints(field_value, constraints)
            if not is_valid:
                return False, f"Field '{field_name}': {error}"
        
        # Ensure either data or rows is present for row topics
        if normalized_topic in ("extracted_rows_topic", "clean_rows_topic"):
            if "data" not in message and "rows" not in message:
                return False, "Missing required field: data or rows"
        if normalized_topic == "metadata_topic":
            has_event_type = bool(str(message.get("event_type") or "").strip())
            has_metadata_type = bool(str(message.get("metadata_type") or "").strip())
            if not has_event_type and not has_metadata_type:
                return False, "Missing required field: event_type or metadata_type"
        return True, None
    
    @classmethod
    def get_schema(cls, topic: str) -> Optional[Dict[str, Any]]:
        """
        Get the schema definition for a topic.
        
        Args:
            topic: Kafka topic name
            
        Returns:
            Schema dictionary or None if not defined
        """
        return cls.SCHEMAS.get(resolve_validation_topic(topic))
    
    @classmethod
    def list_topics(cls) -> List[str]:
        """
        Get list of all topics with defined schemas.
        
        Returns:
            List of topic names
        """
        return list(cls.SCHEMAS.keys())
