"""
API Key Manager Module
Handles creation, validation, and management of API keys
for authenticating external API calls.
"""

import secrets
import hashlib
from typing import Optional
from dataclasses import dataclass, field, asdict

from .config import config, save_config


@dataclass
class ApiKeyInfo:
    """Information about an API key"""
    key_hash: str          # SHA-256 hash of the key
    prefix: str            # First 8 chars for identification
    name: str              # Human-readable label
    created_at: float      # Unix timestamp
    last_used_at: float = 0.0
    enabled: bool = True
    raw_key: str = ""      # Full key value for admin copy


class ApiKeyManager:
    """
    Manages API keys for the proxy server.
    Keys are stored in config with both raw value and SHA-256 hash so the admin UI can copy them later.
    
    Usage:
        manager = ApiKeyManager()
        key = manager.create_key("my-app")
        if manager.validate_key(key):
            # allow access
    """

    def __init__(self) -> None:
        self._keys: dict[str, ApiKeyInfo] = {}

    @staticmethod
    def _hash_key(key: str) -> str:
        """Hash an API key with SHA-256"""
        return hashlib.sha256(key.encode()).hexdigest()

    @staticmethod
    def generate_key() -> str:
        """
        Generate a cryptographically secure API key.
        Format: sk-{48 random hex chars}
        """
        return "sk-" + secrets.token_hex(24)

    def create_key(self, name: str = "") -> str:
        """
        Create a new API key.
        Returns the full key (only shown once!).
        The key is stored as a SHA-256 hash.
        """
        raw_key = self.generate_key()
        key_hash = self._hash_key(raw_key)
        
        info = ApiKeyInfo(
            raw_key=raw_key,
            key_hash=key_hash,
            prefix=raw_key[:11],  # "sk-" + first 8 hex chars
            name=name or f"key-{len(self._keys) + 1}",
            created_at=__import__('time').time(),
        )
        
        self._keys[key_hash] = info
        self._save_keys()
        
        return raw_key

    def validate_key(self, key: str) -> bool:
        """
        Validate an API key.
        Returns True if the key is valid and enabled.
        """
        if not key:
            return False
        
        key_hash = self._hash_key(key)
        info = self._keys.get(key_hash)
        
        if info and info.enabled:
            info.last_used_at = __import__('time').time()
            self._save_keys()
            return True
        
        return False

    def list_keys(self) -> list[ApiKeyInfo]:
        """List all API keys."""
        return list(self._keys.values())

    def revoke_key(self, prefix_or_name: str) -> bool:
        """
        Revoke (disable) an API key by prefix or name.
        Returns True if a key was found and revoked.
        """
        for info in self._keys.values():
            if info.prefix == prefix_or_name or info.name == prefix_or_name:
                info.enabled = False
                self._save_keys()
                return True
        return False

    def enable_key(self, prefix_or_name: str) -> bool:
        """Re-enable a previously revoked key"""
        for info in self._keys.values():
            if info.prefix == prefix_or_name or info.name == prefix_or_name:
                info.enabled = True
                self._save_keys()
                return True
        return False

    def delete_key(self, prefix_or_name: str) -> bool:
        """Permanently delete a key"""
        for key_hash, info in list(self._keys.items()):
            if info.prefix == prefix_or_name or info.name == prefix_or_name:
                del self._keys[key_hash]
                self._save_keys()
                return True
        return False

    def reload(self) -> None:
        """Reload keys from config file"""
        self._load_keys()

    def _save_keys(self) -> None:
        """Save keys to config file"""
        data = [asdict(k) for k in self._keys.values()]
        config.api_keys = data
        save_config(config)

    def _load_keys(self) -> None:
        """Load keys from config file"""
        self._keys.clear()
        for item in config.api_keys:
            # Backward compatibility: item might be a plain string (old format)
            if isinstance(item, str):
                # Old format: raw key string
                key_hash = self._hash_key(item)
                self._keys[key_hash] = ApiKeyInfo(
                    raw_key=item,
                    key_hash=key_hash,
                    prefix=item[:11] if len(item) >= 11 else item,
                    name="legacy-key",
                    created_at=0.0,
                    enabled=True,
                )
            elif isinstance(item, dict):
                migrated_item = dict(item)
                migrated_item.setdefault("raw_key", "")
                info = ApiKeyInfo(**migrated_item)
                self._keys[info.key_hash] = info


# Global singleton
api_key_manager = ApiKeyManager()

# Load existing keys on import
api_key_manager._load_keys()
