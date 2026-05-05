"""
Configuration Management Module
Handles app configuration with file-based persistence
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".kimi2api")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


@dataclass
class AppConfig:
    """Application configuration"""

    # Server settings
    host: str = "127.0.0.1"
    port: int = 8080

    # Kimi token (JWT or refresh token)
    kimi_token: str = ""

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


def get_default_config() -> AppConfig:
    """Get default configuration"""
    return AppConfig()


def ensure_config_dir() -> None:
    """Ensure config directory exists"""
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load_config() -> AppConfig:
    """Load configuration from file, fall back to defaults"""
    ensure_config_dir()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            config = AppConfig()
            for key, value in data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            return config
        except Exception as e:
            print(f"[Config] Failed to load config: {e}, using defaults")
    return get_default_config()


def save_config(config: AppConfig) -> None:
    """Save configuration to file"""
    ensure_config_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(asdict(config), f, indent=2, ensure_ascii=False)


# Global config instance
config = load_config()


def reload_config() -> AppConfig:
    """Reload configuration from file"""
    global config
    config = load_config()
    return config
