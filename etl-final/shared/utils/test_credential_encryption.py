"""
Tests for Credential Encryption Utility

Tests encryption, decryption, and credential handling functionality.
"""
import unittest
import os
from credential_encryption import CredentialEncryption, get_encryption_instance


class TestCredentialEncryption(unittest.TestCase):
    """Test cases for credential encryption and decryption"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Use a test secret key
        self.test_secret = "test-secret-key-for-unit-tests"
        self.encryption = CredentialEncryption(secret_key=self.test_secret)
    
    def test_encrypt_decrypt_basic(self):
        """Test basic encryption and decryption"""
        plaintext = "my_secure_password123"
        
        # Encrypt
        encrypted = self.encryption.encrypt(plaintext)
        
        # Verify encrypted is different from plaintext
        self.assertNotEqual(encrypted, plaintext)
        self.assertTrue(len(encrypted) > 0)
        
        # Decrypt
        decrypted = self.encryption.decrypt(encrypted)
        
        # Verify decrypted matches original
        self.assertEqual(decrypted, plaintext)
    
    def test_encrypt_empty_string(self):
        """Test encryption of empty string"""
        encrypted = self.encryption.encrypt("")
        self.assertEqual(encrypted, "")
        
        decrypted = self.encryption.decrypt("")
        self.assertEqual(decrypted, "")
    
    def test_encrypt_special_characters(self):
        """Test encryption with special characters"""
        passwords = [
            "p@ssw0rd!",
            "password with spaces",
            "пароль",  # Cyrillic
            "密码",    # Chinese
            "🔒🔑",    # Emojis
            "tab\ttab",
            "newline\nnewline"
        ]
        
        for password in passwords:
            encrypted = self.encryption.encrypt(password)
            decrypted = self.encryption.decrypt(encrypted)
            self.assertEqual(decrypted, password, f"Failed for password: {password}")
    
    def test_encrypt_long_password(self):
        """Test encryption of very long password"""
        long_password = "a" * 1000
        encrypted = self.encryption.encrypt(long_password)
        decrypted = self.encryption.decrypt(encrypted)
        self.assertEqual(decrypted, long_password)
    
    def test_different_keys_produce_different_ciphertext(self):
        """Test that different keys produce different encrypted output"""
        plaintext = "password123"
        
        encryption1 = CredentialEncryption(secret_key="key1")
        encryption2 = CredentialEncryption(secret_key="key2")
        
        encrypted1 = encryption1.encrypt(plaintext)
        encrypted2 = encryption2.encrypt(plaintext)
        
        # Different keys should produce different ciphertext
        self.assertNotEqual(encrypted1, encrypted2)
    
    def test_wrong_key_fails_decryption(self):
        """Test that decryption with wrong key fails"""
        plaintext = "password123"
        
        encryption1 = CredentialEncryption(secret_key="key1")
        encryption2 = CredentialEncryption(secret_key="key2")
        
        encrypted = encryption1.encrypt(plaintext)
        
        # Attempting to decrypt with wrong key should raise exception
        with self.assertRaises(Exception):
            encryption2.decrypt(encrypted)
    
    def test_encrypt_credentials_dict(self):
        """Test encrypting credentials in a dictionary"""
        credentials = {
            "db_type": "mysql",
            "host": "localhost",
            "user": "admin",
            "password": "secret_password",
            "database": "mydb",
            "port": 3306
        }
        
        encrypted_creds = self.encryption.encrypt_credentials(credentials)
        
        # Verify password is encrypted
        self.assertNotEqual(encrypted_creds["password"], credentials["password"])
        self.assertTrue(encrypted_creds["_password_encrypted"])
        
        # Verify other fields unchanged
        self.assertEqual(encrypted_creds["db_type"], credentials["db_type"])
        self.assertEqual(encrypted_creds["host"], credentials["host"])
        self.assertEqual(encrypted_creds["user"], credentials["user"])
        self.assertEqual(encrypted_creds["database"], credentials["database"])
        self.assertEqual(encrypted_creds["port"], credentials["port"])
    
    def test_decrypt_credentials_dict(self):
        """Test decrypting credentials in a dictionary"""
        credentials = {
            "db_type": "postgres",
            "host": "db.example.com",
            "user": "dbuser",
            "password": "my_password",
            "database": "production",
            "port": 5432
        }
        
        # Encrypt
        encrypted_creds = self.encryption.encrypt_credentials(credentials)
        
        # Decrypt
        decrypted_creds = self.encryption.decrypt_credentials(encrypted_creds)
        
        # Verify password is decrypted correctly
        self.assertEqual(decrypted_creds["password"], credentials["password"])
        
        # Verify _password_encrypted flag is removed
        self.assertNotIn("_password_encrypted", decrypted_creds)
        
        # Verify other fields unchanged
        self.assertEqual(decrypted_creds["db_type"], credentials["db_type"])
        self.assertEqual(decrypted_creds["host"], credentials["host"])
    
    def test_encrypt_credentials_without_password(self):
        """Test encrypting credentials dict without password field"""
        credentials = {
            "db_type": "mysql",
            "host": "localhost",
            "user": "admin"
        }
        
        encrypted_creds = self.encryption.encrypt_credentials(credentials)
        
        # Should return unchanged
        self.assertEqual(encrypted_creds, credentials)
    
    def test_decrypt_unencrypted_credentials(self):
        """Test decrypting credentials that are not encrypted"""
        credentials = {
            "password": "plaintext_password",
            "_password_encrypted": False
        }
        
        # Should return unchanged with warning
        decrypted_creds = self.encryption.decrypt_credentials(credentials)
        self.assertEqual(decrypted_creds["password"], "plaintext_password")
    
    def test_singleton_instance(self):
        """Test that get_encryption_instance returns singleton"""
        instance1 = get_encryption_instance()
        instance2 = get_encryption_instance()
        
        # Should be the same instance
        self.assertIs(instance1, instance2)
    
    def test_deterministic_encryption_with_same_key(self):
        """Test that same key produces consistent encryption/decryption"""
        plaintext = "test_password"
        
        # Create two instances with same key
        enc1 = CredentialEncryption(secret_key="same_key")
        enc2 = CredentialEncryption(secret_key="same_key")
        
        # Encrypt with first instance
        encrypted = enc1.encrypt(plaintext)
        
        # Decrypt with second instance (same key)
        decrypted = enc2.decrypt(encrypted)
        
        # Should successfully decrypt
        self.assertEqual(decrypted, plaintext)
    
    def test_environment_variable_key(self):
        """Test that encryption uses environment variable if no key provided"""
        # Set environment variable
        test_key = "env_test_key"
        os.environ["CREDENTIAL_SECRET_KEY"] = test_key
        
        try:
            # Create instance without explicit key
            encryption = CredentialEncryption()
            
            plaintext = "password123"
            encrypted = encryption.encrypt(plaintext)
            decrypted = encryption.decrypt(encrypted)
            
            self.assertEqual(decrypted, plaintext)
        finally:
            # Clean up
            if "CREDENTIAL_SECRET_KEY" in os.environ:
                del os.environ["CREDENTIAL_SECRET_KEY"]
    
    def test_round_trip_integration(self):
        """Test full round-trip: encrypt in connector, decrypt in extractor"""
        # Simulate connector service
        original_credentials = {
            "db_type": "mysql",
            "host": "localhost",
            "user": "root",
            "password": "super_secret_password",
            "database": "testdb",
            "port": 3306
        }
        
        # Connector encrypts
        connector_encryption = CredentialEncryption(secret_key="shared_secret")
        kafka_message = connector_encryption.encrypt_credentials(original_credentials)
        
        # Verify password is encrypted in Kafka message
        self.assertNotEqual(kafka_message["password"], original_credentials["password"])
        self.assertTrue(kafka_message["_password_encrypted"])
        
        # Simulate extractor service receiving message
        extractor_encryption = CredentialEncryption(secret_key="shared_secret")
        decrypted_credentials = extractor_encryption.decrypt_credentials(kafka_message)
        
        # Verify password is correctly decrypted
        self.assertEqual(decrypted_credentials["password"], original_credentials["password"])
        self.assertNotIn("_password_encrypted", decrypted_credentials)


if __name__ == "__main__":
    unittest.main()
