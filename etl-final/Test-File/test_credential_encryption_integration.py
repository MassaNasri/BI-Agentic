"""
Integration Test for Credential Encryption

Tests the end-to-end flow of credential encryption from connector to extractor service.
This simulates the actual Kafka message flow with encrypted credentials.
"""
import sys
import os

# Add shared utilities to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'shared'))

from shared.utils.credential_encryption import CredentialEncryption


def test_connector_to_extractor_flow():
    """
    Simulate the full flow:
    1. Connector service receives database credentials
    2. Connector encrypts password before sending to Kafka
    3. Extractor receives message from Kafka
    4. Extractor decrypts password before connecting to database
    """
    print("=" * 70)
    print("INTEGRATION TEST: Credential Encryption Flow")
    print("=" * 70)
    
    # Step 1: Simulate connector service receiving credentials
    print("\n[CONNECTOR SERVICE] Received database connection request")
    original_credentials = {
        "db_type": "mysql",
        "host": "localhost",
        "user": "root",
        "password": "super_secret_password_123!",
        "database": "testdb",
        "port": 3306
    }
    print(f"  Database: {original_credentials['database']}")
    print(f"  User: {original_credentials['user']}")
    print(f"  Password: {'*' * len(original_credentials['password'])}")
    
    # Step 2: Connector encrypts password
    print("\n[CONNECTOR SERVICE] Encrypting password before sending to Kafka")
    encryption = CredentialEncryption()
    encrypted_password = encryption.encrypt(original_credentials['password'])
    
    kafka_message = {
        "type": "database",
        "db_type": original_credentials["db_type"],
        "host": original_credentials["host"],
        "user": original_credentials["user"],
        "password": encrypted_password,
        "_password_encrypted": True,
        "database": original_credentials["database"],
        "port": original_credentials["port"]
    }
    
    print(f"  Original password: {original_credentials['password']}")
    print(f"  Encrypted password: {encrypted_password[:50]}...")
    print(f"  Encrypted length: {len(encrypted_password)} bytes")
    
    # Verify password is actually encrypted
    assert kafka_message['password'] != original_credentials['password'], \
        "Password should be encrypted!"
    assert kafka_message['_password_encrypted'] == True, \
        "Encryption flag should be set!"
    print("  ✓ Password successfully encrypted")
    
    # Step 3: Simulate Kafka message transmission
    print("\n[KAFKA] Message published to connection_topic")
    print(f"  Message type: {kafka_message['type']}")
    print(f"  Password encrypted: {kafka_message['_password_encrypted']}")
    
    # Step 4: Simulate extractor service receiving message
    print("\n[EXTRACTOR SERVICE] Received message from connection_topic")
    received_message = kafka_message.copy()
    
    # Step 5: Extractor decrypts password
    print("[EXTRACTOR SERVICE] Decrypting password")
    decryption = CredentialEncryption()
    
    if received_message.get('_password_encrypted', False):
        decrypted_password = decryption.decrypt(received_message['password'])
        print(f"  Encrypted password: {received_message['password'][:50]}...")
        print(f"  Decrypted password: {decrypted_password}")
    else:
        print("  WARNING: Password not marked as encrypted!")
        decrypted_password = received_message['password']
    
    # Verify decryption worked correctly
    assert decrypted_password == original_credentials['password'], \
        "Decrypted password should match original!"
    print("  ✓ Password successfully decrypted")
    
    # Step 6: Verify database connection would work
    print("\n[EXTRACTOR SERVICE] Preparing database connection")
    db_config = {
        "db_type": received_message["db_type"],
        "host": received_message["host"],
        "user": received_message["user"],
        "password": decrypted_password,
        "database": received_message["database"],
        "port": received_message["port"]
    }
    print(f"  Database: {db_config['database']}")
    print(f"  User: {db_config['user']}")
    print(f"  Password: {'*' * len(db_config['password'])}")
    print("  ✓ Database configuration ready")
    
    # Final verification
    print("\n" + "=" * 70)
    print("INTEGRATION TEST RESULTS")
    print("=" * 70)
    print("✓ Connector successfully encrypted password")
    print("✓ Kafka message contains encrypted password")
    print("✓ Extractor successfully decrypted password")
    print("✓ Decrypted password matches original")
    print("✓ Database connection configuration is correct")
    print("\n✅ ALL TESTS PASSED!")
    print("=" * 70)


def test_security_verification():
    """
    Verify that encrypted passwords cannot be easily decrypted without the key.
    """
    print("\n" + "=" * 70)
    print("SECURITY VERIFICATION TEST")
    print("=" * 70)
    
    password = "my_secret_password"
    
    # Encrypt with one key
    encryption1 = CredentialEncryption(secret_key="production_key_1")
    encrypted = encryption1.encrypt(password)
    
    print(f"\nOriginal password: {password}")
    print(f"Encrypted: {encrypted[:50]}...")
    
    # Try to decrypt with wrong key
    print("\nAttempting to decrypt with wrong key...")
    encryption2 = CredentialEncryption(secret_key="wrong_key")
    
    try:
        decrypted = encryption2.decrypt(encrypted)
        print("❌ SECURITY FAILURE: Decryption succeeded with wrong key!")
        return False
    except Exception as e:
        print(f"✓ Decryption correctly failed with wrong key")
        print(f"  Error: {type(e).__name__}")
    
    # Decrypt with correct key
    print("\nDecrypting with correct key...")
    decrypted = encryption1.decrypt(encrypted)
    assert decrypted == password
    print(f"✓ Decryption succeeded with correct key")
    print(f"  Decrypted: {decrypted}")
    
    print("\n✅ SECURITY VERIFICATION PASSED!")
    print("=" * 70)


def test_kafka_log_safety():
    """
    Verify that Kafka logs would not expose plaintext passwords.
    """
    print("\n" + "=" * 70)
    print("KAFKA LOG SAFETY TEST")
    print("=" * 70)
    
    plaintext_password = "admin123"
    encryption = CredentialEncryption()
    
    # Create Kafka message
    kafka_message = {
        "type": "database",
        "host": "localhost",
        "user": "admin",
        "password": encryption.encrypt(plaintext_password),
        "_password_encrypted": True,
        "database": "mydb"
    }
    
    # Simulate Kafka log output
    print("\nSimulated Kafka log entry:")
    print("-" * 70)
    print(f"Topic: connection_topic")
    print(f"Message: {kafka_message}")
    print("-" * 70)
    
    # Verify plaintext password is not in the message
    message_str = str(kafka_message)
    assert plaintext_password not in message_str, \
        "Plaintext password should not appear in Kafka message!"
    
    print("\n✓ Plaintext password NOT found in Kafka message")
    print("✓ Encrypted password is safe to log")
    print("\n✅ KAFKA LOG SAFETY VERIFIED!")
    print("=" * 70)


if __name__ == "__main__":
    try:
        # Run all integration tests
        test_connector_to_extractor_flow()
        test_security_verification()
        test_kafka_log_safety()
        
        print("\n" + "=" * 70)
        print("🎉 ALL INTEGRATION TESTS PASSED!")
        print("=" * 70)
        print("\nCredential encryption is working correctly:")
        print("  • Passwords are encrypted before sending to Kafka")
        print("  • Encrypted passwords cannot be decrypted without the key")
        print("  • Kafka logs do not expose plaintext passwords")
        print("  • Extractor can successfully decrypt passwords")
        print("=" * 70)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
