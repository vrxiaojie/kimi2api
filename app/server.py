"""
OpenAI-Compatible API Server
Flask-based server that exposes /v1/chat/completions and other endpoints,
proxying requests to Kimi's internal API.
"""

import os
import json
import re
import time
import uuid
import logging
from typing import Optional

from dataclasses import asdict

from flask import Flask, request, Response, jsonify, stream_with_context, render_template, send_from_directory

from .config import (
    CONFIG_FILE,
    config,
    reload_config,
    save_config,
    KimiAccount,
    get_active_account,
    set_active_account,
    get_active_kimi_token,
)
from .auth import token_manager, validate_kimi_token
from .kimi_client import KimiClient
from .stream_handler import KimiStreamHandler, generate_sse_events
from .apikey_manager import api_key_manager

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("kimi2api")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
WEBUI_ROOT = os.path.join(PROJECT_ROOT, "webui")
TEMPLATES_DIR = os.path.join(WEBUI_ROOT, "templates")
STATIC_DIR = os.path.join(WEBUI_ROOT, "static")

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)

# Public paths that don't require authentication
PUBLIC_PATHS = {"/", "/health", "/stats", "/v1/models"}


def _serialize_account(account: KimiAccount, include_token: bool = False) -> dict:
    data = asdict(account)
    if not include_token:
        token = data.get("token", "")
        if token:
            data["token"] = f"{token[:6]}...{token[-4:]}" if len(token) > 10 else "***"
    return data


def _serialize_api_key(api_key) -> dict:
    return {
        "key": api_key.raw_key,
        "copy_available": bool(api_key.raw_key),
        "prefix": api_key.prefix,
        "name": api_key.name,
        "created_at": api_key.created_at,
        "last_used_at": api_key.last_used_at,
        "enabled": api_key.enabled,
    }


def _serialize_state() -> dict:
    active_account = get_active_account(config)
    return {
        "config": {
            "host": config.host,
            "port": config.port,
            "log_level": config.log_level,
            "enable_api_key": config.enable_api_key,
            "config_file": CONFIG_FILE,
            "kimi_token_configured": bool(get_active_kimi_token(config)),
            "active_account_id": config.active_account_id,
            "accounts_count": len(config.accounts),
        },
        "accounts": [_serialize_account(account) for account in config.accounts],
        "active_account_id": active_account.id if active_account else "",
        "models": [
            {"openai_model": openai_model, "kimi_model": kimi_model}
            for openai_model, kimi_model in config.model_mapping.items()
        ],
        "api_keys": [_serialize_api_key(api_key) for api_key in api_key_manager.list_keys()],
    }


def _set_account_validation_state(account: KimiAccount, status: str, message: str) -> None:
    now = time.time()
    account.validation_status = status
    account.validation_message = message
    account.validated_at = now
    account.updated_at = now


def _collect_completion_result(response, model: str, request_id: str, enable_thinking: bool) -> dict:
    """Read a non-streaming Kimi response and aggregate the final assistant payload."""
    handler = KimiStreamHandler(
        model=model,
        conversation_id=request_id,
        enable_thinking=enable_thinking,
    )

    full_content = ""
    reasoning_content = ""
    tool_calls = []

    chunks = []

    def collector(chunk):
        if chunk is not None:
            chunks.append(chunk)

    for raw_bytes in response.iter_content(chunk_size=8192):
        if raw_bytes:
            handler.process_raw_bytes(raw_bytes, collector)

    for chunk in chunks:
        if chunk.get("choices"):
            delta = chunk["choices"][0].get("delta", {})
            if "content" in delta and delta["content"]:
                full_content += delta["content"]
            if "reasoning_content" in delta and delta["reasoning_content"]:
                reasoning_content += delta["reasoning_content"]
            if "tool_calls" in delta and delta["tool_calls"]:
                for tool_call in delta["tool_calls"]:
                    tool_calls.append(tool_call)

    return {
        "content": full_content.strip(),
        "reasoning_content": reasoning_content.strip(),
        "tool_calls": tool_calls,
    }


def _probe_account_chat(account: KimiAccount) -> dict:
    """Send a minimal chat message through the account token and require a normal reply."""
    request_id = _generate_request_id()
    model_name = config.model_mapping.get("kimi-k2.6", "kimi-k2.6")
    kimi_client = KimiClient(account.token)
    response = kimi_client.chat_completion(
        messages=[{"role": "user", "content": "你好"}],
        model=model_name,
        original_model="kimi-k2.6",
        stream=False,
        temperature=0.1,
        enable_thinking=False,
        enable_web_search=False,
        tools=None,
    )

    completion = _collect_completion_result(response, model_name, request_id, False)
    has_normal_reply = bool(
        completion["content"] or completion["reasoning_content"] or completion["tool_calls"]
    )
    if not has_normal_reply:
        raise RuntimeError("Account probe completed but did not return a normal reply")

    excerpt = completion["content"] or completion["reasoning_content"] or "工具调用返回正常"
    return {
        "valid": True,
        "probe_message": "你好",
        "reply_excerpt": excerpt[:120],
        "model": model_name,
        "tool_calls": completion["tool_calls"],
    }


def _mask_credentials(data: dict) -> dict:
    masked = dict(data)
    if masked.get("token"):
        token = str(masked["token"])
        masked["token"] = f"{token[:6]}...{token[-4:]}" if len(token) > 10 else "***"
    return masked


def _extract_auth_token_from_curl(curl_command: str) -> str:
    raw_text = str(curl_command or "")
    if not raw_text.strip():
        raise ValueError("Missing required field: curl")

    match = re.search(r"auth=([^;]+)", raw_text, flags=re.IGNORECASE)
    if not match:
        raise ValueError("未能在 curl 文本中找到 auth=...;，请确认复制的是包含 Cookie 的请求")

    token = match.group(1).strip().strip('"').strip("'")
    if not token:
        raise ValueError("提取到的 auth token 为空，请确认复制的 curl 内容完整")

    return token


def _create_account_from_token(
    *,
    name: str,
    token: str,
    auth_method: str,
    notes: str,
    enabled: bool,
    activate: bool,
    source: str,
) -> tuple[KimiAccount, dict]:
    validation = validate_kimi_token(token)
    if not validation.get("valid"):
        raise ValueError(validation.get("error", "Token validation failed"))

    now = time.time()
    account = KimiAccount(
        id=f"acct-{uuid.uuid4().hex[:12]}",
        name=name,
        auth_method=auth_method,
        token=token,
        token_type=validation.get("token_type") or auth_method or "jwt",
        created_at=now,
        updated_at=now,
        enabled=enabled,
        notes=notes,
        user_id=(validation.get("account_info") or {}).get("user_id", ""),
        source=source,
        validation_status="untested",
        validation_message="Token 已保存，尚未发送测试消息",
    )

    config.accounts.append(account)
    if activate or not config.active_account_id:
        set_active_account(config, account.id)
    save_config(config)
    return account, validation


def _require_api_key():
    """Check API key authentication if enabled"""
    if not config.enable_api_key or not config.api_keys:
        return None  # No auth required

    if request.path in PUBLIC_PATHS:
        return None

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": {"message": "Missing or invalid Authorization header", "type": "authentication_error"}}), 401

    provided_key = auth_header[7:]
    if not api_key_manager.validate_key(provided_key):
        return jsonify({"error": {"message": "Invalid API key", "type": "authentication_error"}}), 401

    return None


def _get_kimi_client() -> KimiClient:
    """Get a KimiClient instance with the configured token"""
    token = get_active_kimi_token(config)
    if not token:
        raise ValueError("Kimi token is not configured. Use 'kimi2api config set-token <your_token>' first.")
    return KimiClient(token)


def _extract_user_input(messages: list[dict]) -> Optional[str]:
    """Extract the last user message content for logging"""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                content = " ".join(text_parts)
            if content:
                return str(content)[:100]
    return None


def _generate_request_id() -> str:
    """Generate a unique request ID (OpenAI-style)"""
    return f"chatcmpl-{uuid.uuid4().hex[:24]}"


def _infer_model_features(model: str) -> tuple[bool, bool]:
    """Infer thinking/search features from the public model name."""
    model_lower = model.lower()
    enable_thinking = "thinking" in model_lower or "think" in model_lower or "r1" in model_lower
    enable_web_search = "search" in model_lower
    return enable_thinking, enable_web_search


# ============================================================
# Routes
# ============================================================

@app.route("/", methods=["GET"])
def root():
    """Root endpoint - health check"""
    return jsonify({
        "service": "kimi2api",
        "version": "1.0.0",
        "status": "running",
        "admin": "/admin",
        "endpoints": {
            "chat_completions": "/v1/chat/completions",
            "models": "/v1/models",
        },
    })


@app.route("/admin", methods=["GET"])
def admin():
    """Render the web admin dashboard."""
    return render_template("admin.html")


@app.route("/admin/static/<path:filename>")
def admin_static(filename):
    """Serve admin static files (CSS, JS)."""
    admin_static_dir = os.path.join(STATIC_DIR, "admin")
    response = send_from_directory(admin_static_dir, filename, conditional=False, max_age=0)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers.pop("ETag", None)
    return response


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok"})


@app.route("/stats", methods=["GET"])
def stats():
    """Server statistics"""
    return jsonify({
        "api_keys_count": len(api_key_manager.list_keys()),
        "accounts_count": len(config.accounts),
        "active_account_id": config.active_account_id,
        "kimi_token_configured": bool(get_active_kimi_token(config)),
        "kimi_token_type": token_manager.detect_token_type(get_active_kimi_token(config)) if get_active_kimi_token(config) else "none",
    })


@app.route("/v1/models", methods=["GET"])
def list_models():
    """List available models (OpenAI-compatible)"""
    auth_error = _require_api_key()
    if auth_error:
        return auth_error

    models = [
        {
            "id": "kimi-k2.6",
            "object": "model",
            "created": 1700000000,
            "owned_by": "kimi2api",
        },
    ]

    # Also list mapped models
    for openai_name in config.model_mapping:
        if openai_name != "kimi-k2.6":
            models.append({
                "id": openai_name,
                "object": "model",
                "created": 1700000000,
                "owned_by": "kimi2api",
            })

    return jsonify({"object": "list", "data": models})


@app.route("/admin/api/bootstrap", methods=["GET"])
def admin_bootstrap():
    """Return the full management state for the web dashboard."""
    return jsonify(_serialize_state())


@app.route("/admin/api/config", methods=["GET", "PUT"])
def admin_config():
    """Read or update core server configuration."""
    if request.method == "GET":
        return jsonify(_serialize_state()["config"])

    payload = request.get_json(force=True, silent=True) or {}

    if "host" in payload and payload["host"]:
        config.host = str(payload["host"]).strip()
    if "port" in payload and payload["port"]:
        config.port = int(payload["port"])
    if "log_level" in payload and payload["log_level"]:
        config.log_level = str(payload["log_level"]).upper()
    if "enable_api_key" in payload:
        config.enable_api_key = bool(payload["enable_api_key"])

    if "active_account_id" in payload and payload["active_account_id"]:
        active_account = set_active_account(config, str(payload["active_account_id"]))
        if not active_account:
            return jsonify({"error": {"message": "Active account not found", "type": "invalid_request_error"}}), 404

    save_config(config)
    return jsonify(_serialize_state()["config"])


@app.route("/admin/api/accounts", methods=["GET", "POST"])
def admin_accounts():
    """List accounts or create a new Kimi account."""
    if request.method == "GET":
        return jsonify({
            "accounts": [_serialize_account(account) for account in config.accounts],
            "active_account_id": config.active_account_id,
        })

    payload = request.get_json(force=True, silent=True) or {}
    name = str(payload.get("name") or "").strip()
    token = str(payload.get("token") or "").strip()
    auth_method = str(payload.get("auth_method") or "jwt").strip().lower()
    notes = str(payload.get("notes") or "").strip()
    enabled = bool(payload.get("enabled", True))
    activate = bool(payload.get("activate", True))

    if not name:
        return jsonify({"error": {"message": "Missing required field: name", "type": "invalid_request_error"}}), 400
    if not token:
        return jsonify({"error": {"message": "Missing required field: token", "type": "invalid_request_error"}}), 400

    try:
        account, validation = _create_account_from_token(
            name=name,
            token=token,
            auth_method=auth_method or "jwt",
            notes=notes,
            enabled=enabled,
            activate=activate,
            source="jwt",
        )
    except ValueError as error:
        return jsonify({"error": {"message": str(error), "type": "validation_error"}}), 400

    return jsonify({
        "account": _serialize_account(account),
        "validation": validation,
        "active_account_id": config.active_account_id,
    }), 201


@app.route("/admin/api/accounts/import-curl", methods=["POST"])
def admin_accounts_import_curl():
    """Create an account by extracting auth token from a browser-copied curl command."""
    payload = request.get_json(force=True, silent=True) or {}
    name = str(payload.get("name") or "").strip()
    notes = str(payload.get("notes") or "").strip()
    curl_command = str(payload.get("curl") or "")
    activate = bool(payload.get("activate", True))

    try:
        token = _extract_auth_token_from_curl(curl_command)
        account_name = name or f"Kimi Curl {time.strftime('%m-%d %H:%M')}"
        account, validation = _create_account_from_token(
            name=account_name,
            token=token,
            auth_method="oauth",
            notes=notes,
            enabled=True,
            activate=activate,
            source="curl",
        )
    except ValueError as error:
        return jsonify({"error": {"message": str(error), "type": "validation_error"}}), 400

    return jsonify({
        "account": _serialize_account(account),
        "validation": validation,
        "active_account_id": config.active_account_id,
        "import_method": "curl",
    }), 201


@app.route("/admin/api/accounts/<account_id>", methods=["PUT", "DELETE"])
def admin_account_detail(account_id: str):
    """Update or delete an account."""
    account = next((item for item in config.accounts if item.id == account_id), None)
    if not account:
        return jsonify({"error": {"message": "Account not found", "type": "not_found"}}), 404

    if request.method == "DELETE":
        config.accounts = [item for item in config.accounts if item.id != account_id]
        if config.active_account_id == account_id:
            if config.accounts:
                config.active_account_id = config.accounts[0].id
                set_active_account(config, config.active_account_id)
            else:
                config.active_account_id = ""
                config.kimi_token = ""
        save_config(config)
        return jsonify({"deleted": True, "id": account_id, "active_account_id": config.active_account_id})

    payload = request.get_json(force=True, silent=True) or {}
    if "name" in payload and str(payload["name"]).strip():
        account.name = str(payload["name"]).strip()
    if "notes" in payload:
        account.notes = str(payload["notes"] or "").strip()
    if "enabled" in payload:
        account.enabled = bool(payload["enabled"])
    if "auth_method" in payload and payload["auth_method"]:
        account.auth_method = str(payload["auth_method"]).strip().lower()
    if "token" in payload and str(payload["token"]).strip():
        token = str(payload["token"]).strip()
        validation = validate_kimi_token(token)
        if not validation.get("valid"):
            return jsonify({"error": {"message": validation.get("error", "Token validation failed"), "type": "validation_error"}}), 400
        account.token = token
        account.token_type = validation.get("token_type") or account.token_type
        account.user_id = (validation.get("account_info") or {}).get("user_id", account.user_id)
    account.updated_at = time.time()

    if config.active_account_id == account.id:
        config.kimi_token = account.token

    save_config(config)
    return jsonify({"account": _serialize_account(account), "active_account_id": config.active_account_id})


@app.route("/admin/api/accounts/<account_id>/activate", methods=["POST"])
def admin_account_activate(account_id: str):
    """Mark an account as the active Kimi token."""
    active_account = set_active_account(config, account_id)
    if not active_account:
        return jsonify({"error": {"message": "Account not found", "type": "not_found"}}), 404

    save_config(config)
    return jsonify({"active_account_id": active_account.id, "account": _serialize_account(active_account)})


@app.route("/admin/api/accounts/<account_id>/enabled", methods=["POST"])
def admin_account_enabled(account_id: str):
    """Enable or disable an account."""
    account = next((item for item in config.accounts if item.id == account_id), None)
    if not account:
        return jsonify({"error": {"message": "Account not found", "type": "not_found"}}), 404

    payload = request.get_json(force=True, silent=True) or {}
    enabled = bool(payload.get("enabled"))
    account.enabled = enabled
    account.updated_at = time.time()

    if not enabled and config.active_account_id == account.id:
        config.active_account_id = ""
        config.kimi_token = ""

    save_config(config)
    return jsonify({
        "account": _serialize_account(account),
        "active_account_id": _serialize_state()["active_account_id"],
    })


@app.route("/admin/api/accounts/<account_id>/validate", methods=["POST"])
def admin_account_validate(account_id: str):
    """Validate an account by sending a real probe message through Kimi."""
    account = next((item for item in config.accounts if item.id == account_id), None)
    if not account:
        return jsonify({"error": {"message": "Account not found", "type": "not_found"}}), 404

    try:
        validation = _probe_account_chat(account)
        account.last_used_at = time.time()
        _set_account_validation_state(account, "passed", f"测试消息“你好”已收到正常回复：{validation['reply_excerpt']}")
        if config.active_account_id == account.id:
            config.kimi_token = account.token
        save_config(config)
        return jsonify({
            **validation,
            "status": account.validation_status,
            "message": account.validation_message,
            "validated_at": account.validated_at,
        })
    except Exception as error:
        _set_account_validation_state(account, "failed", str(error))
        save_config(config)
        return jsonify({
            "valid": False,
            "status": account.validation_status,
            "message": account.validation_message,
            "probe_message": "你好",
            "error": str(error),
            "validated_at": account.validated_at,
        }), 400


@app.route("/admin/api/models", methods=["GET", "POST"])
def admin_models():
    """List or create model mappings."""
    if request.method == "GET":
        return jsonify({"models": _serialize_state()["models"]})

    payload = request.get_json(force=True, silent=True) or {}
    openai_model = str(payload.get("openai_model") or "").strip()
    kimi_model = str(payload.get("kimi_model") or "").strip()

    if not openai_model or not kimi_model:
        return jsonify({"error": {"message": "Missing required fields: openai_model and kimi_model", "type": "invalid_request_error"}}), 400

    config.model_mapping[openai_model] = kimi_model
    save_config(config)
    return jsonify({"openai_model": openai_model, "kimi_model": kimi_model}), 201


@app.route("/admin/api/models/<path:openai_model>", methods=["DELETE"])
def admin_model_delete(openai_model: str):
    """Delete a model mapping."""
    if openai_model not in config.model_mapping:
        return jsonify({"error": {"message": "Model mapping not found", "type": "not_found"}}), 404

    del config.model_mapping[openai_model]
    save_config(config)
    return jsonify({"deleted": True, "openai_model": openai_model})


@app.route("/admin/api/api-keys", methods=["GET", "POST"])
def admin_api_keys():
    """List or create API keys."""
    if request.method == "GET":
        return jsonify({"api_keys": [_serialize_api_key(api_key) for api_key in api_key_manager.list_keys()]})

    payload = request.get_json(force=True, silent=True) or {}
    key = api_key_manager.create_key(str(payload.get("name") or ""))
    return jsonify({"key": key, "message": "Save this key - it will not be shown again!"}), 201


@app.route("/admin/api/api-keys/<prefix_or_name>/revoke", methods=["POST"])
def admin_api_key_revoke(prefix_or_name: str):
    """Revoke an API key."""
    if not api_key_manager.revoke_key(prefix_or_name):
        return jsonify({"error": "Key not found"}), 404
    return jsonify({"message": f"Key '{prefix_or_name}' revoked"})


@app.route("/admin/api/api-keys/<prefix_or_name>/enable", methods=["POST"])
def admin_api_key_enable(prefix_or_name: str):
    """Enable an API key."""
    if not api_key_manager.enable_key(prefix_or_name):
        return jsonify({"error": "Key not found"}), 404
    return jsonify({"message": f"Key '{prefix_or_name}' enabled"})


@app.route("/admin/api/api-keys/<prefix_or_name>", methods=["DELETE"])
def admin_api_key_delete(prefix_or_name: str):
    """Delete an API key."""
    if not api_key_manager.delete_key(prefix_or_name):
        return jsonify({"error": "Key not found"}), 404
    return jsonify({"message": f"Key '{prefix_or_name}' deleted"})


@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    """
    OpenAI-compatible chat completions endpoint.
    Proxies requests to Kimi's internal API.
    
    Supports:
    - Streaming (SSE)
    - Thinking/reasoning mode (via reasoning_effort parameter)
    - Web search (via web_search parameter)
    - Tool/function calling (via tools parameter, prompt-based)
    - Multi-turn conversation
    """
    auth_error = _require_api_key()
    if auth_error:
        return auth_error

    try:
        body = request.get_json(force=True)
    except Exception:
        return jsonify({"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}}), 400

    if not body:
        return jsonify({"error": {"message": "Request body is required", "type": "invalid_request_error"}}), 400

    # Validate required fields
    model = body.get("model", "")
    if not model:
        return jsonify({"error": {"message": "Missing required field: model", "type": "invalid_request_error", "param": "model"}}), 400

    messages = body.get("messages", [])
    if not messages or not isinstance(messages, list):
        return jsonify({"error": {"message": "Missing required field: messages", "type": "invalid_request_error", "param": "messages"}}), 400

    # Extract parameters
    stream = body.get("stream", False)
    temperature = body.get("temperature")
    tools = body.get("tools")

    # Feature flags
    enable_web_search = body.get("web_search", False)
    # Support both reasoning_effort and reasoningEffort (camelCase for AI SDK compatibility)
    reasoning_effort = body.get("reasoning_effort") or body.get("reasoningEffort")
    enable_thinking = reasoning_effort in ("low", "medium", "high") if reasoning_effort else False

    inferred_thinking, inferred_web_search = _infer_model_features(model)
    if not enable_thinking:
        enable_thinking = inferred_thinking
    if not enable_web_search:
        enable_web_search = inferred_web_search

    # Map model name
    actual_model = config.model_mapping.get(model, model)

    # Extract user input for logging
    user_input = _extract_user_input(messages)

    request_id = _generate_request_id()
    logger.info(f"[{request_id}] Chat completion: model={model} -> {actual_model}, stream={stream}, "
                f"thinking={enable_thinking}, search={enable_web_search}, tools={len(tools) if tools else 0}, "
                f"input={user_input}")

    try:
        kimi_client = _get_kimi_client()
    except ValueError as e:
        return jsonify({"error": {"message": str(e), "type": "configuration_error"}}), 500

    if stream:
        return _handle_stream(kimi_client, messages, actual_model, temperature,
                             enable_thinking, enable_web_search, tools, request_id, model)
    else:
        return _handle_non_stream(kimi_client, messages, actual_model, temperature,
                                  enable_thinking, enable_web_search, tools, request_id, model)


def _handle_stream(
    kimi_client: KimiClient,
    messages: list[dict],
    model: str,
    temperature: Optional[float],
    enable_thinking: bool,
    enable_web_search: bool,
    tools: Optional[list[dict]],
    request_id: str,
    original_model: str,
) -> Response:
    """Handle streaming chat completion"""

    def generate():
        try:
            response = kimi_client.chat_completion(
                messages=messages,
                model=model,
                original_model=original_model,
                stream=True,
                temperature=temperature,
                enable_thinking=enable_thinking,
                enable_web_search=enable_web_search,
                tools=tools,
            )

            handler = KimiStreamHandler(
                model=model,
                conversation_id=request_id,
                enable_thinking=enable_thinking,
            )

            sent_role = False
            buffer = b""

            def emit_chunk(chunk: Optional[dict]):
                nonlocal sent_role
                if chunk is None:
                    return
                # Inject role on first content-bearing chunk
                if not sent_role and chunk.get("choices"):
                    delta = chunk["choices"][0].get("delta", {})
                    if "content" in delta or "reasoning_content" in delta:
                        delta["role"] = "assistant"
                        sent_role = True
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            for raw_bytes in response.iter_content(chunk_size=8192):
                if not raw_bytes:
                    continue
                buffer += raw_bytes
                # Process accumulated buffer through handler
                # The handler processes gRPC-Web frames and calls collector
                chunks = []
                def collector(chunk):
                    if chunk is not None:
                        chunks.append(chunk)

                handler.process_raw_bytes(raw_bytes, collector)

                for chunk in chunks:
                    if not sent_role and chunk.get("choices"):
                        delta = chunk["choices"][0].get("delta", {})
                        if "content" in delta or "reasoning_content" in delta:
                            delta["role"] = "assistant"
                            sent_role = True
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"[{request_id}] Stream error: {e}")
            error_chunk = {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": f"Error: {str(e)}"},
                    "finish_reason": "error",
                }],
            }
            yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Request-Id": request_id,
        },
    )


def _handle_non_stream(
    kimi_client: KimiClient,
    messages: list[dict],
    model: str,
    temperature: Optional[float],
    enable_thinking: bool,
    enable_web_search: bool,
    tools: Optional[list[dict]],
    request_id: str,
    original_model: str,
) -> Response:
    """Handle non-streaming chat completion"""
    try:
        response = kimi_client.chat_completion(
            messages=messages,
            model=model,
            original_model=original_model,
            stream=False,
            temperature=temperature,
            enable_thinking=enable_thinking,
            enable_web_search=enable_web_search,
            tools=tools,
        )

        completion = _collect_completion_result(response, model, request_id, enable_thinking)
        full_content = completion["content"]
        reasoning_content = completion["reasoning_content"]
        tool_calls = completion["tool_calls"]

        # Build OpenAI-compatible response
        message = {"role": "assistant", "content": None if tool_calls else full_content}
        if reasoning_content:
            message["reasoning_content"] = reasoning_content
        if tool_calls:
            message["tool_calls"] = tool_calls

        finish_reason = "tool_calls" if tool_calls else "stop"

        result = {
            "id": request_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
        return jsonify(result)

    except Exception as e:
        logger.error(f"[{request_id}] Non-stream error: {e}")
        return jsonify({"error": {"message": str(e), "type": "api_error"}}), 500


# ============================================================
# Management API (API key management)
# ============================================================

@app.route("/v0/management/api-keys", methods=["GET"])
def list_api_keys():
    """List all API keys (prefixes only, not full keys)"""
    keys = api_key_manager.list_keys()
    return jsonify({
        "keys": [
            {
                "prefix": k.prefix,
                "name": k.name,
                "created_at": k.created_at,
                "last_used_at": k.last_used_at,
                "enabled": k.enabled,
            }
            for k in keys
        ]
    })


@app.route("/v0/management/api-keys", methods=["POST"])
def create_api_key():
    """Create a new API key"""
    data = request.get_json(silent=True) or {}
    name = data.get("name", "")
    key = api_key_manager.create_key(name)
    return jsonify({"key": key, "message": "Save this key - it will not be shown again!"})


@app.route("/v0/management/api-keys/<prefix_or_name>", methods=["DELETE"])
def revoke_api_key(prefix_or_name: str):
    """Revoke (disable) an API key"""
    success = api_key_manager.revoke_key(prefix_or_name)
    if success:
        return jsonify({"message": f"Key '{prefix_or_name}' revoked"})
    return jsonify({"error": "Key not found"}), 404


# ============================================================
# Server runner
# ============================================================

def create_app() -> Flask:
    """Create and configure the Flask app"""
    return app


def run_server(host: str = None, port: int = None, debug: bool = False):
    """Run the server. Prefers gunicorn if available, falls back to Flask dev server."""
    import subprocess
    host = host or config.host
    port = port or config.port

    logger.info(f"Starting kimi2api server on {host}:{port}")
    logger.info(f"API Key auth: {'enabled' if config.enable_api_key and config.api_keys else 'disabled'}")
    logger.info(f"Kimi token: {'configured' if config.kimi_token else 'NOT CONFIGURED'}")

    # Try gunicorn first for production-grade concurrency
    try:
        import gunicorn  # noqa: F401
        logger.info("Using gunicorn WSGI server")
        subprocess.run([
            "gunicorn",
            "--bind", f"{host}:{port}",
            "--workers", "2",
            "--threads", "4",
            "--timeout", "120",
            "--access-logfile", "-",
            "--error-logfile", "-",
            "app.server:create_app()",
        ], check=True)
    except (ImportError, FileNotFoundError):
        logger.warning("gunicorn not found, falling back to Flask development server (not recommended for production)")
        app.run(host=host, port=port, debug=debug, threaded=True)
