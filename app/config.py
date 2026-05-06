"""
Configuration Management Module
Handles app configuration with file-based persistence.
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
CONFIG_FILE = os.environ.get("KIMI2API_CONFIG") or os.path.join(PROJECT_ROOT, "config.json")
LEGACY_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".kimi2api", "config.json")


@dataclass
class KimiAccount:
    """Saved Kimi account entry."""

    id: str
    name: str
    auth_method: str = "jwt"
    token: str = ""
    token_type: str = "jwt"
    created_at: float = 0.0
    updated_at: float = 0.0
    last_used_at: float = 0.0
    enabled: bool = True
    notes: str = ""
    user_id: str = ""
    source: str = "manual"
    validation_status: str = "unknown"
    validation_message: str = ""
    validated_at: float = 0.0


def _detect_token_type(token: str) -> str:
    if token.startswith("eyJ") and token.count(".") == 2:
        return "jwt"
    return "refresh"


def _build_legacy_account(token: str) -> KimiAccount:
    token_type = _detect_token_type(token)
    now = time.time()
    return KimiAccount(
        id="legacy-kimi-token",
        name="Default Kimi Account",
        auth_method=token_type,
        token=token,
        token_type=token_type,
        created_at=now,
        updated_at=now,
        source="legacy",
    )


@dataclass
class AppConfig:
    """Application configuration"""

    # Server settings
    host: str = "127.0.0.1"
    port: int = 8080

    # Kimi token (JWT or refresh token)
    kimi_token: str = ""

    # Saved Kimi accounts
    accounts: list[KimiAccount] = field(default_factory=list)
    active_account_id: str = ""

    # API key settings
    enable_api_key: bool = True
    api_keys: list[str] = field(default_factory=list)

    # Model mapping (OpenAI model name -> Kimi model name)
    model_mapping: dict[str, str] = field(default_factory=lambda: {
        "kimi-k2.6": "kimi-k2.6",
        "kimi-k2.6-thinking": "kimi-k2.6",
    })

    # Log level
    log_level: str = "INFO"

    # Auto-delete chat after completion
    auto_delete_chat: bool = False


def get_default_config() -> AppConfig:
    """Get default configuration"""
    return AppConfig()


def ensure_config_dir() -> None:
    """Ensure config directory exists."""
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)


def _load_config_from_file(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Config] Failed to load {path}: {e}")
        return None


def _coerce_account(value: object) -> Optional[KimiAccount]:
    if not isinstance(value, dict):
        return None

    allowed_keys = {field.name for field in KimiAccount.__dataclass_fields__.values()}
    data = {key: value.get(key) for key in allowed_keys if key in value}
    if not data.get("id"):
        data["id"] = f"account-{int(time.time() * 1000)}"
    if not data.get("name"):
        data["name"] = "Kimi Account"
    if not data.get("auth_method"):
        data["auth_method"] = _detect_token_type(str(data.get("token") or ""))
    if not data.get("token_type"):
        data["token_type"] = _detect_token_type(str(data.get("token") or ""))

    return KimiAccount(**data)


def get_account_by_id(config_value: AppConfig, account_id: str) -> Optional[KimiAccount]:
    for account in config_value.accounts:
        if account.id == account_id:
            return account
    return None


def get_active_account(config_value: Optional[AppConfig] = None) -> Optional[KimiAccount]:
    current = config_value or config
    if not current.accounts:
        return None

    if current.active_account_id:
        active_account = get_account_by_id(current, current.active_account_id)
        if active_account and active_account.enabled:
            return active_account

    for account in current.accounts:
        if account.enabled:
            return account

    return None


def set_active_account(config_value: AppConfig, account_id: str) -> Optional[KimiAccount]:
    account = get_account_by_id(config_value, account_id)
    if not account or not account.enabled:
        return None

    config_value.active_account_id = account.id
    config_value.kimi_token = account.token
    account.updated_at = time.time()
    return account


def get_active_kimi_token(config_value: Optional[AppConfig] = None) -> str:
    current = config_value or config
    active_account = get_active_account(current)
    if active_account and active_account.token:
        return active_account.token
    return current.kimi_token


def _normalize_config(config_value: AppConfig) -> AppConfig:
    if not config_value.accounts and config_value.kimi_token:
        config_value.accounts = [_build_legacy_account(config_value.kimi_token)]
        config_value.active_account_id = config_value.accounts[0].id

    if config_value.accounts:
        active_account = get_active_account(config_value)
        if active_account:
            config_value.active_account_id = active_account.id
            if active_account.token:
                config_value.kimi_token = active_account.token
        else:
            config_value.active_account_id = ""
            config_value.kimi_token = ""

    return config_value


def load_config() -> AppConfig:
    """Load configuration from file, fall back to defaults"""
    ensure_config_dir()
    data = _load_config_from_file(CONFIG_FILE) or _load_config_from_file(LEGACY_CONFIG_FILE)
    if not data:
        return get_default_config()

    config_value = AppConfig()
    for key, value in data.items():
        if key == "accounts" and isinstance(value, list):
            config_value.accounts = [account for account in (_coerce_account(item) for item in value) if account]
        elif hasattr(config_value, key):
            setattr(config_value, key, value)

    return _normalize_config(config_value)


def save_config(config: AppConfig) -> None:
    """Save configuration to file"""
    ensure_config_dir()
    _normalize_config(config)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(asdict(config), f, indent=2, ensure_ascii=False)


# Global config instance
config = load_config()


def reload_config() -> AppConfig:
    """Reload configuration from file"""
    global config
    config = load_config()
    return config
