import base64
import os
import hashlib
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

def _get_fernet():
    secret = os.getenv("SECRET_KEY", "default-fallback-key-for-hrms-12345")
    # Generate 32 bytes from SHA256 hash of SECRET_KEY to use as Fernet key
    key_bytes = hashlib.sha256(secret.encode('utf-8')).digest()
    key_b64 = base64.urlsafe_b64encode(key_bytes)
    return Fernet(key_b64)

def encrypt_token(plain_text: str) -> str:
    """Encrypts cleartext to cipher string using Fernet derived key."""
    if not plain_text:
        return ""
    f = _get_fernet()
    return f.encrypt(plain_text.encode('utf-8')).decode('utf-8')

def decrypt_token(cipher_text: str) -> str:
    """Decrypts cipher string back to cleartext."""
    if not cipher_text:
        return ""
    f = _get_fernet()
    return f.decrypt(cipher_text.encode('utf-8')).decode('utf-8')
