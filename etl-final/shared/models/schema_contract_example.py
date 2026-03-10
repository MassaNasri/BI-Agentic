"""
Schema Contract Framework - Usage Examples

This file demonstrates how to use the Schema Contract Framework
for data validation in the ETL pipeline.
"""
from datetime import datetime
from schema_contract import (
    DataType,
    ConstraintType,
    Constraint,
    FieldDefinition,
    SchemaContract,
    SchemaEvolutionRecord
)


def example_1_basic_schema():
    """Example 1: Create a basic schema contract."""
    print("\n=== Example 1: Basic Schema Contract ===\n")
    
    # Define a simple user schema
    user_schema = SchemaContract(
        schema_id="user_schema",
        version="1.0.0",
        fields=[
            FieldDefinition(
                name="id",
                type=DataType.INTEGER,
                nullable=False,
                description="User ID"
            ),
            FieldDefinition(
                name="name",
                type=DataType.STRING,
                nullable=False,
                description="User full name"
            ),
            FieldDefinition(
                name="email",
                type=DataType.STRING,
                nullable=False,
                description="User email address"
            )
        ],
        description="Basic user data schema"
    )
    
    # Validate a valid row
    valid_row = {
        "id": 1,
        "name": "John Doe",
        "email": "john.doe@example.com"
    }
    
    result = user_schema.validate_row(valid_row)
    print(f"Valid row: {result.is_valid}")
    print(f"Quality score: {result.quality_score}")
    print(f"Violations: {result.violations}")
    
    # Validate an invalid row (missing required field)
    invalid_row = {
        "id": 2,
        "name": "Jane Doe"
        # Missing 'email'
    }
    
    result = user_schema.validate_row(invalid_row)
    print(f"\nInvalid row: {result.is_valid}")
    print(f"Quality score: {result.quality_score}")
    print(f"Violations: {result.violations}")


def example_2_constraints():
    """Example 2: Schema with validation constraints."""
    print("\n=== Example 2: Schema with Constraints ===\n")
    
    # Define a product schema with constraints
    product_schema = SchemaContract(
        schema_id="product_schema",
        version="1.0.0",
        fields=[
            FieldDefinition(
                name="sku",
                type=DataType.STRING,
                nullable=False,
                constraints=[
                    Constraint(
                        constraint_type=ConstraintType.REGEX,
                        value=r'^[A-Z]{3}-\d{6}$',
                        error_message="SKU must be in format ABC-123456"
                    )
                ],
                description="Product SKU"
            ),
            FieldDefinition(
                name="price",
                type=DataType.FLOAT,
                nullable=False,
                constraints=[
                    Constraint(ConstraintType.MIN, 0.01),
                    Constraint(ConstraintType.MAX, 999999.99)
                ],
                description="Product price"
            ),
            FieldDefinition(
                name="category",
                type=DataType.STRING,
                nullable=False,
                constraints=[
                    Constraint(
                        constraint_type=ConstraintType.ENUM,
                        value=["electronics", "clothing", "food", "books"]
                    )
                ],
                description="Product category"
            ),
            FieldDefinition(
                name="stock",
                type=DataType.INTEGER,
                nullable=False,
                constraints=[
                    Constraint(ConstraintType.MIN, 0)
                ],
                description="Stock quantity"
            )
        ],
        description="Product catalog schema"
    )
    
    # Valid product
    valid_product = {
        "sku": "ABC-123456",
        "price": 29.99,
        "category": "electronics",
        "stock": 100
    }
    
    result = product_schema.validate_row(valid_product)
    print(f"Valid product: {result.is_valid}")
    print(f"Quality score: {result.quality_score}")
    
    # Invalid product (bad SKU format)
    invalid_product = {
        "sku": "invalid-sku",
        "price": 29.99,
        "category": "electronics",
        "stock": 100
    }
    
    result = product_schema.validate_row(invalid_product)
    print(f"\nInvalid product (bad SKU): {result.is_valid}")
    print(f"Violations: {result.violations}")
    
    # Invalid product (negative price)
    invalid_product2 = {
        "sku": "ABC-123456",
        "price": -10.00,
        "category": "electronics",
        "stock": 100
    }
    
    result = product_schema.validate_row(invalid_product2)
    print(f"\nInvalid product (negative price): {result.is_valid}")
    print(f"Violations: {result.violations}")


def example_3_email_validation():
    """Example 3: Email format validation."""
    print("\n=== Example 3: Email Format Validation ===\n")
    
    contact_schema = SchemaContract(
        schema_id="contact_schema",
        version="1.0.0",
        fields=[
            FieldDefinition(
                name="email",
                type=DataType.STRING,
                nullable=False,
                constraints=[
                    Constraint(ConstraintType.FORMAT, "email")
                ]
            ),
            FieldDefinition(
                name="website",
                type=DataType.STRING,
                nullable=True,
                constraints=[
                    Constraint(ConstraintType.FORMAT, "url")
                ]
            )
        ],
        description="Contact information schema"
    )
    
    # Valid contact
    valid_contact = {
        "email": "contact@example.com",
        "website": "https://example.com"
    }
    
    result = contact_schema.validate_row(valid_contact)
    print(f"Valid contact: {result.is_valid}")
    
    # Invalid email
    invalid_contact = {
        "email": "not-an-email",
        "website": "https://example.com"
    }
    
    result = contact_schema.validate_row(invalid_contact)
    print(f"\nInvalid email: {result.is_valid}")
    print(f"Violations: {result.violations}")


def example_4_serialization():
    """Example 4: Schema serialization and deserialization."""
    print("\n=== Example 4: Schema Serialization ===\n")
    
    # Create a schema
    original_schema = SchemaContract(
        schema_id="test_schema",
        version="1.0.0",
        fields=[
            FieldDefinition(
                name="id",
                type=DataType.INTEGER,
                nullable=False
            ),
            FieldDefinition(
                name="name",
                type=DataType.STRING,
                nullable=False,
                constraints=[
                    Constraint(ConstraintType.MIN, 3),
                    Constraint(ConstraintType.MAX, 50)
                ]
            )
        ],
        description="Test schema for serialization"
    )
    
    # Serialize to dictionary
    schema_dict = original_schema.to_dict()
    print("Serialized schema:")
    print(f"  Schema ID: {schema_dict['schema_id']}")
    print(f"  Version: {schema_dict['version']}")
    print(f"  Fields: {len(schema_dict['fields'])}")
    
    # Deserialize back to object
    restored_schema = SchemaContract.from_dict(schema_dict)
    print(f"\nRestored schema:")
    print(f"  Schema ID: {restored_schema.schema_id}")
    print(f"  Version: {restored_schema.version}")
    print(f"  Fields: {len(restored_schema.fields)}")
    
    # Verify it works the same
    test_row = {"id": 1, "name": "Test"}
    result = restored_schema.validate_row(test_row)
    print(f"\nValidation with restored schema: {result.is_valid}")


def example_5_schema_evolution():
    """Example 5: Track schema evolution."""
    print("\n=== Example 5: Schema Evolution Tracking ===\n")
    
    # Record a schema change
    evolution = SchemaEvolutionRecord(
        schema_id="user_schema",
        from_version="1.0.0",
        to_version="1.1.0",
        changes=[
            "Added field 'phone' (nullable)",
            "Added email format constraint"
        ],
        change_type="ADDITION",
        backward_compatible=True,
        created_by="admin"
    )
    
    print(f"Evolution ID: {evolution.evolution_id}")
    print(f"Schema: {evolution.schema_id}")
    print(f"Version change: {evolution.from_version} -> {evolution.to_version}")
    print(f"Changes:")
    for change in evolution.changes:
        print(f"  - {change}")
    print(f"Backward compatible: {evolution.backward_compatible}")
    
    # Serialize evolution record
    evolution_dict = evolution.to_dict()
    print(f"\nSerialized evolution record: {len(evolution_dict)} fields")


def example_6_quality_scoring():
    """Example 6: Quality score calculation."""
    print("\n=== Example 6: Quality Score Calculation ===\n")
    
    schema = SchemaContract(
        schema_id="quality_test",
        version="1.0.0",
        fields=[
            FieldDefinition(name="field1", type=DataType.STRING, nullable=False),
            FieldDefinition(name="field2", type=DataType.STRING, nullable=True),
            FieldDefinition(name="field3", type=DataType.STRING, nullable=True),
            FieldDefinition(name="field4", type=DataType.STRING, nullable=True)
        ]
    )
    
    # All fields present
    row1 = {"field1": "a", "field2": "b", "field3": "c", "field4": "d"}
    result1 = schema.validate_row(row1)
    print(f"All fields present - Quality score: {result1.quality_score:.2f}")
    
    # Some optional fields missing
    row2 = {"field1": "a", "field2": "b"}
    result2 = schema.validate_row(row2)
    print(f"Some optional missing - Quality score: {result2.quality_score:.2f}")
    
    # Only required field
    row3 = {"field1": "a"}
    result3 = schema.validate_row(row3)
    print(f"Only required field - Quality score: {result3.quality_score:.2f}")


def example_7_complex_validation():
    """Example 7: Complex real-world validation scenario."""
    print("\n=== Example 7: Complex Validation Scenario ===\n")
    
    # Define a comprehensive order schema
    order_schema = SchemaContract(
        schema_id="order_schema",
        version="2.0.0",
        fields=[
            FieldDefinition(
                name="order_id",
                type=DataType.STRING,
                nullable=False,
                constraints=[
                    Constraint(ConstraintType.REGEX, r'^ORD-\d{8}$')
                ]
            ),
            FieldDefinition(
                name="customer_email",
                type=DataType.STRING,
                nullable=False,
                constraints=[
                    Constraint(ConstraintType.FORMAT, "email")
                ]
            ),
            FieldDefinition(
                name="order_date",
                type=DataType.TIMESTAMP,
                nullable=False
            ),
            FieldDefinition(
                name="total_amount",
                type=DataType.FLOAT,
                nullable=False,
                constraints=[
                    Constraint(ConstraintType.MIN, 0.01),
                    Constraint(ConstraintType.MAX, 1000000.00)
                ]
            ),
            FieldDefinition(
                name="status",
                type=DataType.STRING,
                nullable=False,
                constraints=[
                    Constraint(
                        ConstraintType.ENUM,
                        ["pending", "processing", "shipped", "delivered", "cancelled"]
                    )
                ]
            ),
            FieldDefinition(
                name="items_count",
                type=DataType.INTEGER,
                nullable=False,
                constraints=[
                    Constraint(ConstraintType.MIN, 1),
                    Constraint(ConstraintType.MAX, 100)
                ]
            )
        ],
        description="E-commerce order schema with comprehensive validation"
    )
    
    # Valid order
    valid_order = {
        "order_id": "ORD-12345678",
        "customer_email": "customer@example.com",
        "order_date": "2024-01-15T10:30:00Z",
        "total_amount": 149.99,
        "status": "processing",
        "items_count": 3
    }
    
    result = order_schema.validate_row(valid_order)
    print(f"Valid order: {result.is_valid}")
    print(f"Quality score: {result.quality_score}")
    print(f"Field scores: {result.field_scores}")
    
    # Invalid order (multiple violations)
    invalid_order = {
        "order_id": "INVALID",  # Wrong format
        "customer_email": "not-an-email",  # Invalid email
        "order_date": "2024-01-15T10:30:00Z",
        "total_amount": -50.00,  # Negative amount
        "status": "unknown",  # Invalid status
        "items_count": 0  # Below minimum
    }
    
    result = order_schema.validate_row(invalid_order)
    print(f"\nInvalid order: {result.is_valid}")
    print(f"Quality score: {result.quality_score}")
    print(f"Violations ({len(result.violations)}):")
    for violation in result.violations:
        print(f"  - {violation}")


if __name__ == "__main__":
    print("=" * 60)
    print("Schema Contract Framework - Usage Examples")
    print("=" * 60)
    
    example_1_basic_schema()
    example_2_constraints()
    example_3_email_validation()
    example_4_serialization()
    example_5_schema_evolution()
    example_6_quality_scoring()
    example_7_complex_validation()
    
    print("\n" + "=" * 60)
    print("All examples completed successfully!")
    print("=" * 60)
