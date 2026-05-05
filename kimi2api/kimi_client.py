"""
Kimi Web API Client
Reverse-engineered client for Kimi's internal chat API.
Uses gRPC-Web protocol to communicate with Kimi's ChatService.
"""

import json
import re
import uuid
import struct
import time
from typing import Optional

import requests

from .auth import token_manager, TokenInfo, FAKE_HEADERS
from .tool_parser import TOOL_WRAP_HINT, has_tool_prompt_injected

KIMI_API_BASE = "https://www.kimi.com"
CHAT_PATH = "/apiv2/kimi.gateway.chat.v1.ChatService/Chat"

# gRPC-Web frame constants
GRPC_WEB_FLAG = 0x00


def _generate_kimi_id() -> str:
    """Generate a Kimi-style unique ID (numeric string)"""
    return str(int(time.time() * 1000)) + str(uuid.uuid4().int % 1000000).zfill(6)


def _wrap_urls(text: str) -> str:
    """Wrap URLs in <url> tags as Kimi expects"""
    return re.sub(
        r'https?://(www\.)?[-a-zA-Z0-9@:%._+~#=]{2,256}\.[a-z]{2,6}\b([-a-zA-Z0-9@:%_+.~#?&//=]*)',
        lambda m: f'<url id="" type="url" status="" title="" wc="">{m.group(0)}</url>',
        text,
        flags=re.IGNORECASE,
    )


def _build_grpc_web_frame(payload: bytes) -> bytes:
    """Build a gRPC-Web frame: 1 byte flag (0x00) + 4 bytes big-endian length + payload"""
    length = len(payload)
    return struct.pack(">BI", GRPC_WEB_FLAG, length) + payload


class KimiClient:
    """
    Kimi web API client.
    Translates OpenAI-style requests to Kimi's internal gRPC-Web format.
    """

    def __init__(self, token: str):
        self.token = token

    def _get_token_info(self) -> TokenInfo:
        """Get valid token info, refreshing if needed"""
        return token_manager.acquire_token(self.token)

    def _messages_to_kimi_format(
        self, messages: list[dict], tools: Optional[list[dict]] = None
    ) -> str:
        """
        Convert OpenAI-format messages to Kimi's text format.
        Kimi expects: role:content\n format with special handling for
        system messages, tool calls, and URLs.
        """
        # Check if tool prompt has already been injected by client
        tool_prompt_exists = has_tool_prompt_injected(messages)

        # Process messages including tool calls and tool responses
        processed_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Handle array content (multimodal)
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif part.get("type") == "image_url":
                            text_parts.append("[Image]")
                        elif part.get("type") == "file":
                            text_parts.append("[File]")
                    else:
                        text_parts.append(str(part))
                content = " ".join(text_parts)

            if not content:
                content = ""

            # Handle assistant tool calls - convert to Kimi format
            if role == "assistant" and msg.get("tool_calls"):
                tool_calls_text = "\n".join(
                    f"[call:{tc['function']['name']}]{tc['function']['arguments']}[/call]"
                    for tc in msg["tool_calls"]
                )
                processed_messages.append({
                    "role": "assistant",
                    "content": f"[function_calls]\n{tool_calls_text}\n[/function_calls]",
                })
                continue

            # Handle tool results - convert to user message with TOOL_RESULT prefix
            if role == "tool":
                tool_id = msg.get("tool_call_id", "")
                processed_messages.append({
                    "role": "user",
                    "content": f"[TOOL_RESULT for {tool_id}] {content}",
                })
                continue

            processed_messages.append({"role": role, "content": content})

        # Append TOOL_WRAP_HINT to last user message if tools are present
        # and tool prompt hasn't been injected yet
        if tools and not tool_prompt_exists:
            for i in range(len(processed_messages) - 1, -1, -1):
                if processed_messages[i]["role"] == "user":
                    current_content = processed_messages[i]["content"]
                    if isinstance(current_content, str):
                        processed_messages[i]["content"] = current_content + TOOL_WRAP_HINT
                    break

        # Extract system message
        system_content = ""
        other_messages = []
        for msg in processed_messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                other_messages.append(msg)

        content = ""

        # Prepend system message if exists
        if system_content:
            content = f"system:{system_content}\n"

        # Build content string
        if len(other_messages) < 2:
            # Single message or empty - format directly
            for msg in other_messages:
                text = msg["content"]
                if msg["role"] == "user":
                    text = _wrap_urls(text)
                content += f"{msg['role']}:{text}\n"
        else:
            # Multiple messages - inject focus hint before last message
            latest_message = other_messages[-1]
            has_file_or_image = isinstance(latest_message.get("content"), list) and any(
                isinstance(p, dict) and p.get("type") in ("file", "image_url")
                for p in latest_message["content"]
            )

            if has_file_or_image:
                other_messages.insert(-1, {
                    "role": "system",
                    "content": "Focus on the latest files and messages sent by user",
                })
            else:
                other_messages.insert(-1, {
                    "role": "system",
                    "content": "Focus on the latest message from user",
                })

            for msg in other_messages:
                text = msg["content"]
                if msg["role"] == "user":
                    text = _wrap_urls(text)
                content += f"{msg['role']}:{text}\n"

        # Inject tools prompt at the end to maximize attention
        if tools:
            tools_prompt = _build_tools_prompt(tools)
            content = content.strip() + "\n\n" + tools_prompt

        return content

    def _build_chat_request(
        self,
        messages: list[dict],
        model: str = "kimi-k2.6",
        enable_thinking: bool = False,
        enable_web_search: bool = False,
        tools: Optional[list[dict]] = None,
    ) -> dict:
        """
        Build a Kimi-compatible chat request body in gRPC-Web format.
        """
        # Convert messages to Kimi's text format
        content = self._messages_to_kimi_format(messages, tools)

        request_body = {
            "scenario": "SCENARIO_K2D5",
            "chat_id": "",
            "tools": [{"type": "TOOL_TYPE_SEARCH", "search": {}}] if enable_web_search else [],
            "message": {
                "parent_id": "",
                "role": "user",
                "blocks": [{
                    "message_id": "",
                    "text": {"content": content}
                }],
                "scenario": "SCENARIO_K2D5"
            },
            "options": {
                "thinking": enable_thinking
            }
        }

        return request_body

    def chat_completion(
        self,
        messages: list[dict],
        model: str = "kimi-k2.6",
        original_model: Optional[str] = None,
        stream: bool = True,
        temperature: Optional[float] = None,
        enable_thinking: bool = False,
        enable_web_search: bool = False,
        tools: Optional[list[dict]] = None,
        conversation_id: Optional[str] = None,
        parent_message_id: Optional[str] = None,
    ) -> requests.Response:
        """
        Send a chat completion request to Kimi API.
        Returns the raw HTTP response for streaming or non-streaming.
        
        Note: temperature, conversation_id, parent_message_id are kept for
        API compatibility but not sent to Kimi (matches TS reference).
        """
        token_info = self._get_token_info()

        # Auto-enable features based on the public model name before mapping.
        model_for_detection = original_model or model
        model_lower = model_for_detection.lower()
        if not enable_thinking and ("thinking" in model_lower or "think" in model_lower or "r1" in model_lower):
            enable_thinking = True
            print(f"[KimiClient] Thinking mode enabled (from model name: {model_for_detection})")
        if not enable_web_search and "search" in model_lower:
            enable_web_search = True
            print(f"[KimiClient] Web search enabled (from model name: {model_for_detection})")

        # Build headers - matches TS reference (no R-Device-Id/R-Session-Id)
        headers = {
            **FAKE_HEADERS,
            "Authorization": f"Bearer {token_info.access_token}",
            "Content-Type": "application/connect+json",
        }

        # Build request body in new gRPC-Web format
        body = self._build_chat_request(
            messages=messages,
            model=model,
            enable_thinking=enable_thinking,
            enable_web_search=enable_web_search,
            tools=tools,
        )

        # Debug: print the request body being sent to Kimi
        print(f"[KimiClient] Request body: {json.dumps(body, ensure_ascii=False, indent=2)}")

        url = f"{KIMI_API_BASE}{CHAT_PATH}"

        # Encode body as gRPC-Web frame
        payload_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        grpc_frame = _build_grpc_web_frame(payload_bytes)

        print(f"[KimiClient] Request body length: {len(grpc_frame)}, JSON length: {len(payload_bytes)}")

        response = requests.post(
            url,
            data=grpc_frame,
            headers=headers,
            stream=stream,
            timeout=120,
        )

        print(f"[KimiClient] Completion response status: {response.status_code}")

        if response.status_code == 401:
            token_manager.remove_token(self.token)
            raise ValueError("Kimi token is invalid or expired")

        if response.status_code != 200:
            error_msg = f"Kimi API error: HTTP {response.status_code}"
            try:
                error_data = response.json()
                error_msg = f"Kimi API error: {error_data.get('message', error_data)}"
            except Exception:
                pass
            raise RuntimeError(error_msg)

        return response


def _build_tools_prompt(tools: list[dict]) -> str:
    """
    Build a system prompt describing available tools.
    """
    tool_defs = []
    for tool in tools:
        func = tool.get("function", {})
        name = func.get("name", "")
        desc = func.get("description", "No description")
        params = json.dumps(func.get("parameters", {}), ensure_ascii=False)
        tool_defs.append(f"Tool `{name}`: {desc}. Arguments JSON schema: {params}")

    return f"""## Available Tools
You can invoke the following developer tools. Call a tool only when it is required and follow the JSON schema exactly when providing arguments.

{chr(10).join(tool_defs)}

## Tool Call Protocol
When you decide to call a tool, you MUST respond with NOTHING except a single [function_calls] block exactly like the template below:

[function_calls]
[call:exact_tool_name_from_list]{{"argument": "value"}}[/call]
[/function_calls]

CRITICAL RULES:
1. EVERY tool call MUST start with [call:exact_tool_name] and end with [/call]
2. You MUST use the EXACT tool name as defined in the Available Tools list
3. The content between [call:...] and [/call] MUST be a raw JSON object on ONE LINE - NO LINE BREAKS inside the JSON
4. Do NOT wrap JSON in ```json blocks
5. Do NOT output any other text, explanation, or reasoning before or after the [function_calls] block
6. If you need to call multiple tools, put them all inside the same [function_calls] block, each with its own [call:...]...[/call] wrapper
7. JSON arguments MUST be compact, all on one line, NO pretty printing, NO newlines
8. If you are writing code or regular expressions, you MUST properly escape all backslashes and quotes inside the JSON string."""
