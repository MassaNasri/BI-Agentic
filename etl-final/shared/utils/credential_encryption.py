"""
Credential Encryption Utility

Provides encryption and decryption for sensitive credentials (passwords)
before sending through Kafka messages.

Uses Fernet (symmetric encryption) from cryptography library.
Key is stored in environment variable for security.
"""
import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class CredentialEncryption:
    """
    Handles encryption and decryption of credentials using Fernet symmetric encryption.
    
    The encryption key is derived from a secret key stored in environment variable.
    If no key is provided, a default key is used (NOT RECOMMENDED for production).
    """
    
    def __init__(self, secret_key: Optional[str] = None):
        """
        Initialize the encryption handler.
        
        Args:
            secret_key: Secret key for encryption. If None, reads from CREDENTIAL_SECRET_KEY env var.
        """
        if secret_key is None:
            secret_key = os.environ.get("CREDENTIAL_SECRET_KEY")
        
        if not secret_key:
            # Default key for development (NOT SECURE - should be overridden in production)
            logger.warning(
                "No CREDENTIAL_SECRET_KEY environment variable found. "
                "Using default key. THIS IS NOT SECURE FOR PRODUCTION!"
            )
            secret_key = "etl-pipeline-default-secret-key-change-in-production"
        
        # Derive a proper encryption key from the secret using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'etl-pipeline-salt',  # In production, use a random salt stored securely
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
        self.fernet = Fernet(key)
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string.
        
        Args:
            plaintext: The string to encrypt (e.g., password)
        
        Returns:
            Base64-encoded encrypted string
        """
        if not plaintext:
            return ""
        
        try:
            encrypted_bytes = self.fernet.encrypt(plaintext.encode())
            return encrypted_bytes.decode('utf-8')
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise
    
    def decrypt(self, encrypted: str) -> str:
        """
        Decrypt an encrypted string.
        
        Args:
            encrypted: Base64-encoded encrypted string
        
        Returns:
            Decrypted plaintext string
        """
        if not encrypted:
            return ""
        
        try:
            decrypted_bytes = self.fernet.decrypt(encrypted.encode())
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise
    
    def encrypt_credentials(self, credentials: dict) -> dict:
        """
        Encrypt password field in a credentials dictionary.
        
        Args:
            credentials: Dictionary containing credentials (must have 'password' key)
        
        Returns:
            New dictionary with encrypted password and _encrypted flag
        """
        if 'password' not in credentials:
            return credentials
        
        encrypted_creds = credentials.copy()
        encrypted_creds['password'] = self.encrypt(credentials['password'])
        encrypted_creds['_password_encrypted'] = True
        
        return encrypted_creds
    
    def decrypt_credentials(self, credentials: dict) -> dict:
        """
        Decrypt password field in a credentials dictionary.
        
        Args:
            credentials: Dictionary containing encrypted credentials
        
        Returns:
            New dictionary with decrypted password
        """
        if 'password' not in credentials:
            return credentials
        
        # Check if password is encrypted
        if not credentials.get('_password_encrypted', False):
            logger.warning("Password is not marked as encrypted. Returning as-is.")
            return credentials
        
        decrypted_creds = credentials.copy()
        decrypted_creds['password'] = self.decrypt(credentials['password'])
        del decrypted_creds['_password_encrypted']
        
        return decrypted_creds


# Singleton instance for easy access
_encryption_instance = None


def get_encryption_instance() -> CredentialEncryption:
    """
    Get or create the singleton encryption instance.
    
    Returns:
        CredentialEncryption instance
    """
    global _encryption_instance
    if _encryption_instance is None:
        _encryption_instance = CredentialEncryption()
    return _encryption_instance
