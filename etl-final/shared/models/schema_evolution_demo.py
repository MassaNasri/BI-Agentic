"""
Schema Evolution Detection Demo

This script demonstrates the schema evolution detection capabilities:
1. Infer schema from initial data sample
2. Detect schema changes when new data arrives
3. Track evolution history with alerts
4. Auto-version schemas based on change type

Run: python -m etl-final.shared.models.schema_evolution_demo
"""
import sys
import os

# Add the etl-final directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shared.models.schema_evolution import SchemaInferenceEngine, SchemaEvolutionDetector
from shared.models.schema_contract import SchemaContract, FieldDefinition, DataType


def demo_schema_inference():
    """Demonstrate schema inference from data samples."""
    print("=" * 70)
    print("DEMO 1: Schema Inference from Data")
    print("=" * 70)
    
    engine = SchemaInferenceEngine(min_sample_size=10)
    
    # Sample user data
    user_data = [
        {"id": 1, "name": "Alice", "email": "alice@example.com", "age": 30, "active": True},
        {"id": 2, "name": "Bob", "email": "bob@example.com", "age": 25, "active": True},
        {"id": 3, "name": "Charlie", "email": None, "age": 35, "active": False},
        {"id": 4, "name": "Diana", "email": "diana@example.com", "age": 28, "active": True},
    ]
    
    result = engine.infer_schema(user_data, "user_schema", "1.0.0")
    
    print(f"\nInferred Schema: {result.inferred_schema.schema_id} v{result.inferred_schema.version}")
    print(f"Confidence Score: {result.confidence_score:.2f}")
    print(f"Sample Size: {result.sample_size}")
    print(f"\nFields:")
    for field in result.inferred_schema.fields:
        nullable_str = "nullable" if field.nullable else "required"
        print(f"  - {field.name}: {field.type.value} ({nullable_str})")
        if field.constraints:
            print(f"    Constraints: {[c.constraint_type.value for c in field.constraints]}")
    
    if result.warnings:
        print(f"\nWarnings:")
        for warning in result.warnings:
            print(f"  - {warning}")
    
    return result.inferred_schema


def demo_schema_evolution_addition():
    """Demonstrate detection of field addition (backward compatible)."""
    print("\n" + "=" * 70)
    print("DEMO 2: Schema Evolution - Field Addition (Backward Compatible)")
    print("=" * 70)
    
    # Initial schema
    current_schema = SchemaContract(
        schema_id="user_schema",
        version="1.0.0",
        fields=[
            FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
            FieldDefinition(name="name", type=DataType.STRING, nullable=False),
            FieldDefinition(name="email", type=DataType.STRING, nullable=True),
        ]
    )
    
    print(f"\nCurrent Schema: {current_schema.schema_id} v{current_schema.version}")
    print(f"Fields: {[f.name for f in current_schema.fields]}")
    
    # New data with additional field
    new_data = [
        {"id": 5, "name": "Eve", "email": "eve@example.com", "phone": "555-0001"},
        {"id": 6, "name": "Frank", "email": "frank@example.com", "phone": "555-0002"},
        {"id": 7, "name": "Grace", "email": None, "phone": "555-0003"},
    ]
    
    print(f"\nNew Data Sample: {len(new_data)} rows")
    print(f"New Fields Detected: {list(new_data[0].keys())}")
    
    # Detect evolution
    detector = SchemaEvolutionDetector()
    alert = detector.detect_evolution(current_schema, new_data, auto_version=True)
    
    if alert:
        print(f"\n🔔 ALERT: Schema Evolution Detected!")
        print(f"  Schema ID: {alert.schema_id}")
        print(f"  Old Version: {alert.old_version}")
        print(f"  New Version: {alert.new_version}")
        print(f"  Change Type: {alert.evolution_record.change_type}")
        print(f"  Backward Compatible: {alert.evolution_record.backward_compatible}")
        print(f"  Severity: {alert.severity}")
        print(f"  Changes:")
        for change in alert.evolution_record.changes:
            print(f"    - {change}")
    else:
        print("\n✓ No schema changes detected")


def demo_schema_evolution_removal():
    """Demonstrate detection of field removal (breaking change)."""
    print("\n" + "=" * 70)
    print("DEMO 3: Schema Evolution - Field Removal (Breaking Change)")
    print("=" * 70)
    
    # Initial schema with 4 fields
    current_schema = SchemaContract(
        schema_id="product_schema",
        version="1.5.2",
        fields=[
            FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
            FieldDefinition(name="name", type=DataType.STRING, nullable=False),
            FieldDefinition(name="price", type=DataType.FLOAT, nullable=False),
            FieldDefinition(name="category", type=DataType.STRING, nullable=False),
        ]
    )
    
    print(f"\nCurrent Schema: {current_schema.schema_id} v{current_schema.version}")
    print(f"Fields: {[f.name for f in current_schema.fields]}")
    
    # New data missing 'category' field
    new_data = [
        {"id": 1, "name": "Product A", "price": 19.99},
        {"id": 2, "name": "Product B", "price": 29.99},
        {"id": 3, "name": "Product C", "price": 39.99},
    ]
    
    print(f"\nNew Data Sample: {len(new_data)} rows")
    print(f"Fields in New Data: {list(new_data[0].keys())}")
    
    # Detect evolution
    detector = SchemaEvolutionDetector()
    alert = detector.detect_evolution(current_schema, new_data, auto_version=True)
    
    if alert:
        print(f"\n🚨 ALERT: Breaking Schema Change Detected!")
        print(f"  Schema ID: {alert.schema_id}")
        print(f"  Old Version: {alert.old_version}")
        print(f"  New Version: {alert.new_version} (MAJOR version bump)")
        print(f"  Change Type: {alert.evolution_record.change_type}")
        print(f"  Backward Compatible: {alert.evolution_record.backward_compatible}")
        print(f"  Severity: {alert.severity}")
        print(f"  Changes:")
        for change in alert.evolution_record.changes:
            print(f"    - {change}")


def demo_alert_management():
    """Demonstrate alert history and acknowledgment."""
    print("\n" + "=" * 70)
    print("DEMO 4: Alert History and Management")
    print("=" * 70)
    
    detector = SchemaEvolutionDetector()
    
    # Create multiple schema changes
    schema_v1 = SchemaContract(
        schema_id="order_schema",
        version="1.0.0",
        fields=[
            FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
            FieldDefinition(name="total", type=DataType.FLOAT, nullable=False),
        ]
    )
    
    # Evolution 1: Add customer_id
    data_v2 = [
        {"id": 1, "total": 100.0, "customer_id": 101},
        {"id": 2, "total": 200.0, "customer_id": 102},
    ]
    alert1 = detector.detect_evolution(schema_v1, data_v2, auto_version=True)
    
    # Evolution 2: Add status field
    schema_v2 = SchemaContract(
        schema_id="order_schema",
        version="1.1.0",
        fields=[
            FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
            FieldDefinition(name="total", type=DataType.FLOAT, nullable=False),
            FieldDefinition(name="customer_id", type=DataType.INTEGER, nullable=True),
        ]
    )
    
    data_v3 = [
        {"id": 1, "total": 100.0, "customer_id": 101, "status": "pending"},
        {"id": 2, "total": 200.0, "customer_id": 102, "status": "completed"},
    ]
    alert2 = detector.detect_evolution(schema_v2, data_v3, auto_version=True)
    
    # Display alert history
    print(f"\nAlert History:")
    history = detector.get_alert_history()
    for i, alert in enumerate(history, 1):
        ack_status = "✓ Acknowledged" if alert.acknowledged else "⏳ Pending"
        print(f"\n  Alert {i}: {alert.alert_id[:8]}...")
        print(f"    Version: {alert.old_version} → {alert.new_version}")
        print(f"    Change: {alert.evolution_record.change_type}")
        print(f"    Severity: {alert.severity}")
        print(f"    Status: {ack_status}")
    
    # Acknowledge first alert
    print(f"\n\nAcknowledging alert 1...")
    detector.acknowledge_alert(alert1.alert_id)
    
    # Show unacknowledged alerts
    unacknowledged = detector.get_alert_history(acknowledged=False)
    print(f"\nUnacknowledged Alerts: {len(unacknowledged)}")
    for alert in unacknowledged:
        print(f"  - {alert.alert_id[:8]}... ({alert.old_version} → {alert.new_version})")


def main():
    """Run all demos."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "SCHEMA EVOLUTION DETECTION DEMO" + " " * 22 + "║")
    print("╚" + "=" * 68 + "╝")
    
    try:
        demo_schema_inference()
        demo_schema_evolution_addition()
        demo_schema_evolution_removal()
        demo_alert_management()
        
        print("\n" + "=" * 70)
        print("✓ All demos completed successfully!")
        print("=" * 70)
        print()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
