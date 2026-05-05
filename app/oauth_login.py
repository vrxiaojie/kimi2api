"""
Browser-based OAuth login flow for capturing Kimi tokens automatically.
"""

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .auth import token_manager, validate_kimi_token
from .config import KimiAccount, config, save_config, set_active_account

KIMI_LOGIN_URL = "https://www.kimi.com"
DEFAULT_TIMEOUT_SECONDS = 300
POLL_INTERVAL_SECONDS = 1.0


def _is_probable_token(value: str) -> bool:
    if not value:
        return False

    candidate = value.strip()
    if len(candidate) < 8 or any(ch.isspace() for ch in candidate):
        return False

    if candidate.startswith("eyJ") and candidate.count(".") in (2, 4):
        return True

    if len(candidate) >= 24:
        return True

    return False


def _mask_token(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


@dataclass
class OAuthSessionState:
    session_id: str
    account_name: str
    notes: str = ""
    activate: bool = True
    status: str = "idle"
    message: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    token: str = ""
    token_source: str = ""
    error: str = ""
    account_id: str = ""
    account_name_saved: str = ""
    validation: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "account_name": self.account_name,
            "notes": self.notes,
            "activate": self.activate,
            "status": self.status,
            "message": self.message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "token": _mask_token(self.token),
            "token_source": self.token_source,
            "error": self.error,
            "account_id": self.account_id,
            "account_name_saved": self.account_name_saved,
            "validation": self.validation,
        }


class OAuthLoginManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._session: Optional[OAuthSessionState] = None
        self._worker: Optional[threading.Thread] = None

    def start_login(self, account_name: str, notes: str = "", activate: bool = True) -> dict:
        with self._lock:
            if self._worker and self._worker.is_alive() and self._session and self._session.status not in {"success", "error", "cancelled"}:
                raise RuntimeError("An OAuth login session is already running")

            self._cancel_event = threading.Event()
            session = OAuthSessionState(
                session_id=f"oauth-{uuid.uuid4().hex[:12]}",
                account_name=account_name.strip() or f"Kimi OAuth {time.strftime('%m-%d %H:%M')}",
                notes=notes.strip(),
                activate=activate,
                status="starting",
                message="Opening browser window...",
            )
            self._session = session
            self._worker = threading.Thread(
                target=self._run_login,
                args=(session.session_id,),
                daemon=True,
                name="kimi-oauth-login",
            )
            self._worker.start()
            return session.to_dict()

    def cancel(self) -> dict:
        with self._lock:
            if not self._session:
                return {
                    "cancelled": False,
                    "message": "No OAuth session",
                }
            self._cancel_event.set()
            self._update_state(status="cancelled", message="Cancelling login...", completed=True)
            return {
                "cancelled": True,
                "session": self._session.to_dict(),
            }

    def get_status(self) -> dict:
        with self._lock:
            if not self._session:
                return {
                    "active": False,
                    "session": None,
                }
            return {
                "active": self._worker is not None and self._worker.is_alive() and self._session.status not in {"success", "error", "cancelled"},
                "session": self._session.to_dict(),
            }

    def _update_state(
        self,
        *,
        status: Optional[str] = None,
        message: Optional[str] = None,
        token: Optional[str] = None,
        token_source: Optional[str] = None,
        error: Optional[str] = None,
        validation: Optional[dict] = None,
        account_id: Optional[str] = None,
        account_name_saved: Optional[str] = None,
        completed: bool = False,
    ) -> None:
        with self._lock:
            if not self._session:
                return
            if status is not None:
                self._session.status = status
            if message is not None:
                self._session.message = message
            if token is not None:
                self._session.token = token
            if token_source is not None:
                self._session.token_source = token_source
            if error is not None:
                self._session.error = error
            if validation is not None:
                self._session.validation = validation
            if account_id is not None:
                self._session.account_id = account_id
            if account_name_saved is not None:
                self._session.account_name_saved = account_name_saved
            self._session.updated_at = time.time()
            if completed:
                self._session.completed_at = self._session.updated_at

    def _choose_launch_options(self) -> list[dict]:
        candidates: list[dict] = []
        if os.name == "nt":
            candidates.append({"channel": "msedge", "headless": False})
            candidates.append({"channel": "chrome", "headless": False})
        candidates.append({"headless": False})
        return candidates

    def _run_login(self, session_id: str) -> None:
        browser = None
        context = None
        playwright_ctx = None

        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except Exception as error:
            self._update_state(
                status="error",
                message="Playwright is not available.",
                error=f"{error}. Run: pip install -r requirements.txt and python -m playwright install chromium",
                completed=True,
            )
            return

        try:
            playwright_ctx = sync_playwright().start()
            last_error: Optional[Exception] = None
            for launch_options in self._choose_launch_options():
                try:
                    browser = playwright_ctx.chromium.launch(**launch_options)
                    break
                except Exception as error:
                    last_error = error
                    browser = None

            if not browser:
                raise RuntimeError(
                    f"Unable to launch a browser window: {last_error}. Install Edge/Chrome or run 'python -m playwright install chromium'."
                )

            context = browser.new_context()
            page = context.new_page()

            self._update_state(status="waiting", message="Browser opened. Complete the Kimi login in the new window.")

            found_token: dict[str, str] = {}

            def consume_candidate(candidate: str, source: str) -> bool:
                token_value = (candidate or "").strip()
                if not _is_probable_token(token_value):
                    return False
                if found_token.get("value") == token_value:
                    return False

                found_token["value"] = token_value
                found_token["source"] = source
                self._update_state(status="validating", message=f"Token captured from {source}, validating...", token=token_value, token_source=source)

                validation = validate_kimi_token(token_value)
                if not validation.get("valid"):
                    self._update_state(
                        status="waiting",
                        message="Captured token was invalid. Keep the login window open and continue login.",
                        validation=validation,
                    )
                    return False

                account = self._persist_account(token_value, validation)
                self._update_state(
                    status="success",
                    message="OAuth login complete. Token captured and account saved.",
                    token=token_value,
                    token_source=source,
                    validation=validation,
                    account_id=account.id,
                    account_name_saved=account.name,
                    completed=True,
                )
                return True

            def on_request(request) -> None:
                header_value = request.headers.get("authorization") or request.headers.get("Authorization")
                if not header_value or not header_value.startswith("Bearer "):
                    return
                consume_candidate(header_value[7:], "network header")

            page.on("request", on_request)
            page.goto(KIMI_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

            deadline = time.time() + DEFAULT_TIMEOUT_SECONDS
            local_storage_script = """
                () => {
                    const keys = ['access_token', 'refresh_token', 'token'];
                    const values = [];
                    for (const key of keys) {
                        const fromLocal = window.localStorage ? localStorage.getItem(key) : null;
                        const fromSession = window.sessionStorage ? sessionStorage.getItem(key) : null;
                        if (fromLocal) values.push({ key, value: fromLocal, source: 'localStorage' });
                        if (fromSession) values.push({ key, value: fromSession, source: 'sessionStorage' });
                    }
                    return values;
                }
            """

            while time.time() < deadline:
                if self._cancel_event.is_set():
                    self._update_state(status="cancelled", message="OAuth login cancelled.", completed=True)
                    return

                if self._session and self._session.status == "success":
                    return

                try:
                    values = page.evaluate(local_storage_script)
                    for item in values or []:
                        if consume_candidate(str(item.get("value") or ""), f"{item.get('source')}:{item.get('key')}"):
                            return
                except PlaywrightTimeoutError:
                    pass
                except Exception:
                    pass

                try:
                    cookies = context.cookies([KIMI_LOGIN_URL])
                    for cookie in cookies:
                        if cookie.get("name") not in {"access_token", "refresh_token", "token"}:
                            continue
                        if consume_candidate(str(cookie.get("value") or ""), f"cookie:{cookie.get('name')}"):
                            return
                except Exception:
                    pass

                time.sleep(POLL_INTERVAL_SECONDS)

            self._update_state(
                status="error",
                message="OAuth login timed out.",
                error="No valid token was captured within 5 minutes.",
                completed=True,
            )
        except Exception as error:
            self._update_state(
                status="error",
                message="OAuth login failed.",
                error=str(error),
                completed=True,
            )
        finally:
            try:
                if context:
                    context.close()
            except Exception:
                pass
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            try:
                if playwright_ctx:
                    playwright_ctx.stop()
            except Exception:
                pass

    def _persist_account(self, token: str, validation: dict) -> KimiAccount:
        now = time.time()
        existing = next((account for account in config.accounts if account.token == token), None)
        if existing:
            existing.name = self._session.account_name if self._session else existing.name
            existing.auth_method = "oauth"
            existing.token_type = validation.get("token_type") or token_manager.detect_token_type(token)
            existing.enabled = True
            existing.notes = self._session.notes if self._session else existing.notes
            existing.updated_at = now
            existing.user_id = (validation.get("account_info") or {}).get("user_id", existing.user_id)
            existing.source = "oauth"
            account = existing
        else:
            account = KimiAccount(
                id=f"acct-{uuid.uuid4().hex[:12]}",
                name=self._session.account_name if self._session else f"Kimi OAuth {time.strftime('%m-%d %H:%M')}",
                auth_method="oauth",
                token=token,
                token_type=validation.get("token_type") or token_manager.detect_token_type(token),
                created_at=now,
                updated_at=now,
                enabled=True,
                notes=self._session.notes if self._session else "",
                user_id=(validation.get("account_info") or {}).get("user_id", ""),
                source="oauth",
            )
            config.accounts.append(account)

        if self._session and (self._session.activate or not config.active_account_id):
            set_active_account(config, account.id)
        save_config(config)
        return account


oauth_login_manager = OAuthLoginManager()