"""
Authentication Module - Token Management
Handles JWT and refresh token detection, caching, and refresh
"""

import time
import json
import base64
import hashlib
import uuid
from typing import Optional, Tuple
import requests

KIMI_API_BASE = "https://www.kimi.com"

# Fake browser headers to mimic Chrome
FAKE_HEADERS: dict[str, str] = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Origin": KIMI_API_BASE,
    "R-Timezone": "Asia/Shanghai",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Priority": "u=1, i",
}


class TokenInfo:
    """Cached token information"""

    def __init__(self, access_token: str, refresh_token: str, user_id: str, expires_at: float):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.user_id = user_id
        self.expires_at = expires_at

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class TokenManager:
    """
    Manages Kimi authentication tokens.
    Supports both JWT tokens (starts with eyJ) and refresh tokens.
    """

    _instance: Optional["TokenManager"] = None
    _cache: dict[str, TokenInfo] = {}
    _token_cache_ttl: float = 300  # 5 minutes default TTL

    def __new__(cls) -> "TokenManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def unix_timestamp() -> int:
        """Get current Unix timestamp in seconds"""
        return int(time.time())

    @staticmethod
    def detect_token_type(token: str) -> str:
        """
        Detect token type: 'jwt' or 'refresh'
        JWT tokens start with 'eyJ' and have 3 dot-separated parts.
        """
        if token.startswith("eyJ") and token.count(".") == 2:
            try:
                payload = TokenManager.parse_jwt_payload(token)
                if payload and payload.get("app_id") == "kimi" and payload.get("typ") == "access":
                    return "jwt"
            except Exception:
                pass
        return "refresh"

    @staticmethod
    def parse_jwt_payload(token: str) -> Optional[dict]:
        """Parse the payload section of a JWT token"""
        try:
            parts = token.split(".")
            if len(parts) < 2:
                return None
            payload_b64 = parts[1]
            # Add padding if needed
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            return json.loads(payload_bytes)
        except Exception:
            return None

    @staticmethod
    def extract_user_id_from_jwt(token: str) -> Optional[str]:
        """Extract user ID (sub) from JWT token"""
        payload = TokenManager.parse_jwt_payload(token)
        if payload:
            return payload.get("sub")
        return None

    @staticmethod
    def extract_device_id_from_jwt(token: str) -> Optional[str]:
        """Extract device ID from JWT token"""
        payload = TokenManager.parse_jwt_payload(token)
        if payload:
            return payload.get("device_id")
        return None

    @staticmethod
    def generate_device_id() -> str:
        """Generate a random device ID (matching Kimi's format)"""
        return str(7000000000000000000 + hash(uuid.uuid4().hex) % 999999999999999999)

    @staticmethod
    def generate_session_id() -> str:
        """Generate a random session ID"""
        return str(1700000000000000000 + hash(uuid.uuid4().hex) % 99999999999999999)

    def acquire_token(self, raw_token: str) -> TokenInfo:
        """
        Acquire a valid access token.
        - If JWT: use directly (cached for 5 min)
        - If refresh token: try to refresh, fall back to using directly
        """
        if not raw_token:
            raise ValueError("Kimi token is not configured")

        # Check cache
        if raw_token in self._cache:
            cached = self._cache[raw_token]
            if not cached.is_expired():
                print(f"[Auth] Using cached token, userId: {cached.user_id}")
                return cached

        token_type = self.detect_token_type(raw_token)
        print(f"[Auth] Token type: {token_type}")

        if token_type == "jwt":
            user_id = self.extract_user_id_from_jwt(raw_token) or ""
            token_info = TokenInfo(
                access_token=raw_token,
                refresh_token=raw_token,
                user_id=user_id,
                expires_at=self.unix_timestamp() + self._token_cache_ttl,
            )
            self._cache[raw_token] = token_info
            print(f"[Auth] Using JWT token, userId: {user_id}")
            return token_info

        # Try to use refresh token directly
        print("[Auth] Non-JWT token detected, attempting direct use...")
        token_info = TokenInfo(
            access_token=raw_token,
            refresh_token=raw_token,
            user_id="",
            expires_at=self.unix_timestamp() + self._token_cache_ttl,
        )
        self._cache[raw_token] = token_info
        return token_info

    def refresh_token(self, refresh_token: str) -> Optional[TokenInfo]:
        """
        Attempt to refresh a token using Kimi's token refresh endpoint.
        Returns new TokenInfo or None if refresh fails.
        """
        try:
            url = f"{KIMI_API_BASE}/api/auth/token/refresh"
            headers = {**FAKE_HEADERS, "Authorization": f"Bearer {refresh_token}"}
            resp = requests.get(url, headers=headers, timeout=30)

            if resp.status_code == 200:
                data = resp.json()
                access_token = data.get("access_token") or data.get("token") or refresh_token
                user_id = self.extract_user_id_from_jwt(access_token) or ""
                token_info = TokenInfo(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    user_id=user_id,
                    expires_at=self.unix_timestamp() + self._token_cache_ttl,
                )
                self._cache[refresh_token] = token_info
                print(f"[Auth] Token refreshed successfully, userId: {user_id}")
                return token_info

            print(f"[Auth] Token refresh failed: {resp.status_code}")
            return None
        except Exception as e:
            print(f"[Auth] Token refresh error: {e}")
            return None

    def clear_cache(self) -> None:
        """Clear all cached tokens"""
        self._cache.clear()

    def remove_token(self, raw_token: str) -> None:
        """Remove a specific token from cache"""
        self._cache.pop(raw_token, None)


def validate_kimi_token(raw_token: str) -> dict:
    """Validate a Kimi token against the subscription API."""
    if not raw_token:
        return {
            "valid": False,
            "error": "Token cannot be empty",
        }

    token_type = token_manager.detect_token_type(raw_token)
    try:
        url = f"{KIMI_API_BASE}/apiv2/kimi.gateway.order.v1.SubscriptionService/GetSubscription"
        headers = {
            **FAKE_HEADERS,
            "Authorization": f"Bearer {raw_token}",
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
        }
        response = requests.post(url, json={}, headers=headers, timeout=30)

        if response.status_code != 200:
            return {
                "valid": False,
                "token_type": token_type,
                "error": f"Validation failed ({response.status_code})",
            }

        data = response.json() if response.content else {}
        subscription = data.get("subscription") or {}
        if not subscription:
            return {
                "valid": False,
                "token_type": token_type,
                "error": "Token is invalid or expired",
            }

        return {
            "valid": True,
            "token_type": token_type,
            "account_info": {
                "user_id": subscription.get("userId") or "",
                "name": subscription.get("userName") or "",
                "email": subscription.get("email") or "",
            },
        }
    except Exception as e:
        return {
            "valid": False,
            "token_type": token_type,
            "error": str(e),
        }


# Singleton instance
token_manager = TokenManager()
