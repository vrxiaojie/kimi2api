"""
OpenAI-Compatible API Server
Flask-based server that exposes /v1/chat/completions and other endpoints,
proxying requests to Kimi's internal API.
"""

import json
import time
import uuid
import logging
from typing import Optional

from flask import Flask, request, Response, jsonify, stream_with_context

from .config import config, reload_config
from .auth import token_manager
from .kimi_client import KimiClient
from .stream_handler import KimiStreamHandler, generate_sse_events
from .apikey_manager import api_key_manager

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("kimi2api")

app = Flask(__name__)

# Public paths that don't require authentication
PUBLIC_PATHS = {"/", "/health", "/stats", "/v1/models"}


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
    if not config.kimi_token:
        raise ValueError("Kimi token is not configured. Use 'kimi2api config set-token <your_token>' first.")
    return KimiClient(config.kimi_token)


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
        "endpoints": {
            "chat_completions": "/v1/chat/completions",
            "models": "/v1/models",
        },
    })


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok"})


@app.route("/stats", methods=["GET"])
def stats():
    """Server statistics"""
    return jsonify({
        "api_keys_count": len(api_key_manager.list_keys()),
        "kimi_token_configured": bool(config.kimi_token),
        "kimi_token_type": token_manager.detect_token_type(config.kimi_token) if config.kimi_token else "none",
    })


@app.route("/v1/models", methods=["GET"])
def list_models():
    """List available models (OpenAI-compatible)"""
    auth_error = _require_api_key()
    if auth_error:
        return auth_error

    models = [
        {
            "id": "kimi-k2.5",
            "object": "model",
            "created": 1700000000,
            "owned_by": "kimi2api",
        },
    ]

    # Also list mapped models
    for openai_name in config.model_mapping:
        if openai_name != "kimi-k2.5":
            models.append({
                "id": openai_name,
                "object": "model",
                "created": 1700000000,
                "owned_by": "kimi2api",
            })

    return jsonify({"object": "list", "data": models})


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
                             enable_thinking, enable_web_search, tools, request_id)
    else:
        return _handle_non_stream(kimi_client, messages, actual_model, temperature,
                                  enable_thinking, enable_web_search, tools, request_id)


def _handle_stream(
    kimi_client: KimiClient,
    messages: list[dict],
    model: str,
    temperature: Optional[float],
    enable_thinking: bool,
    enable_web_search: bool,
    tools: Optional[list[dict]],
    request_id: str,
) -> Response:
    """Handle streaming chat completion"""

    def generate():
        try:
            response = kimi_client.chat_completion(
                messages=messages,
                model=model,
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
) -> Response:
    """Handle non-streaming chat completion"""
    try:
        response = kimi_client.chat_completion(
            messages=messages,
            model=model,
            stream=False,
            temperature=temperature,
            enable_thinking=enable_thinking,
            enable_web_search=enable_web_search,
            tools=tools,
        )

        # Read the full response
        handler = KimiStreamHandler(
            model=model,
            conversation_id=request_id,
            enable_thinking=enable_thinking,
        )

        full_content = ""
        reasoning_content = ""

        chunks = []
        def collector(chunk):
            if chunk is not None:
                chunks.append(chunk)

        for raw_bytes in response.iter_content(chunk_size=8192):
            if raw_bytes:
                handler.process_raw_bytes(raw_bytes, collector)

        # Aggregate chunks
        for chunk in chunks:
            if chunk.get("choices"):
                delta = chunk["choices"][0].get("delta", {})
                if "content" in delta and delta["content"]:
                    full_content += delta["content"]
                if "reasoning_content" in delta and delta["reasoning_content"]:
                    reasoning_content += delta["reasoning_content"]

        # Build OpenAI-compatible response
        message = {"role": "assistant", "content": full_content}
        if reasoning_content:
            message["reasoning_content"] = reasoning_content

        result = {
            "id": request_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": "stop",
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
    """Run the Flask development server"""
    host = host or config.host
    port = port or config.port

    logger.info(f"Starting kimi2api server on {host}:{port}")
    logger.info(f"API Key auth: {'enabled' if config.enable_api_key and config.api_keys else 'disabled'}")
    logger.info(f"Kimi token: {'configured' if config.kimi_token else 'NOT CONFIGURED'}")

    app.run(host=host, port=port, debug=debug, threaded=True)
