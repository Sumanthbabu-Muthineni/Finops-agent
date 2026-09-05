"""
Deterministic Cryptographic Engine for UTR Encryption at Rest
Provides deterministic AES-256 encryption to allow sub-millisecond B-Tree indexed searches
on encrypted fields, with reversible decryption for authorized retrieval and display.
"""

import hmac
import hashlib
import base64
from typing import Optional
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend

from backend.config import settings

def derive_key(secret: Optional[str] = None) -> bytes:
    """Derives a deterministic 32-byte (256-bit) AES key from the configured HASH_KEY."""
    key_str = secret or getattr(settings, "HASH_KEY", "finops-evaluator-secret-hashkey-2026")
    return hashlib.sha256(key_str.encode("utf-8")).digest()

def encrypt_utr(plaintext: Optional[str], secret: Optional[str] = None) -> str:
    """
    Deterministically encrypts a UTR string using AES-256-CBC.
    The same plaintext + secret key always generates the exact same ciphertext,
    enabling sub-millisecond PostgreSQL B-Tree indexed equality lookups (WHERE utr_number = '...').
    """
    if not plaintext:
        return ""
    
    s = str(plaintext).strip()
    if not s:
        return ""
        
    key = derive_key(secret)
    # Derive deterministic 16-byte IV via HMAC-SHA256
    iv = hmac.new(key, s.encode("utf-8"), hashlib.sha256).digest()[:16]
    
    # PKCS7 padding to 128-bit block size
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(s.encode("utf-8")) + padder.finalize()
    
    # AES-CBC encryption
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ct = encryptor.update(padded_data) + encryptor.finalize()
    
    # Encode IV + Ciphertext as URL-safe base64 string
    return base64.urlsafe_b64encode(iv + ct).decode("utf-8")

def decrypt_utr(ciphertext_b64: Optional[str], secret: Optional[str] = None) -> str:
    """
    Decrypts an encrypted UTR string using the configured secret key.
    If the string is not valid ciphertext or was stored in plain text, returns it safely as-is.
    """
    if not ciphertext_b64:
        return ""
        
    s = str(ciphertext_b64).strip()
    if not s:
        return ""
        
    try:
        raw = base64.urlsafe_b64decode(s.encode("utf-8"))
        if len(raw) < 32:  # At least 16 bytes IV + 16 bytes minimum padded block
            return s
            
        iv = raw[:16]
        ct = raw[16:]
        key = derive_key(secret)
        
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        padded_data = decryptor.update(ct) + decryptor.finalize()
        
        unpadder = padding.PKCS7(128).unpadder()
        data = unpadder.update(padded_data) + unpadder.finalize()
        return data.decode("utf-8")
    except Exception:
        # Graceful fallback: string is already plain text or encrypted with different format
        return s
