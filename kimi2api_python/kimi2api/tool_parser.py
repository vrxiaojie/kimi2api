"""
Tool Parser Module - Parse tool calls from text content

Supported format:
  Bracket format: [function_calls][call:name]{args}[/call][/function_calls]

All formats are normalized to the standard OpenAI tool_calls format.
"""

import json
import re
import time
from typing import Optional


# ============================================================
# Constants
# ============================================================

# Tool prompt signature markers used to detect already-injected prompts
GENERAL_TOOL_SIGNATURES = [
    "## Available Tools",
    "## Tool Call Protocol",
    "[function_calls]",
    "[call:",
]


def has_tool_prompt_signature(content: str) -> bool:
    """Check if content contains tool prompt signature markers"""
    if not content:
        return False
    for sig in GENERAL_TOOL_SIGNATURES:
        if sig in content:
            return True
    return False


def has_tool_prompt_injected(messages: list[dict]) -> bool:
    """Check if any system/user message already has tool prompt injected"""
    for msg in messages:
        if msg.get("role") in ("system", "user"):
            content = msg.get("content", "")
            if isinstance(content, str) and has_tool_prompt_signature(content):
                print("[Tools] Detected existing tool prompt injection, skipping")
                return True
    return False


# ============================================================
# TOOL_WRAP_HINT - appended to last user message when tools are present
# ============================================================

TOOL_WRAP_HINT = """

IMPORTANT: If you need to use a tool, you MUST wrap the tool call inside a [function_calls] block exactly like:
[function_calls]
[call:exact_tool_name]{"argument":"value"}[/call]
[/function_calls]

CRITICAL - MUST FOLLOW:
- Start with [call:exact_tool_name] (MUST include prefixes like default_api: if present in the tool name)
- Then the JSON arguments ALL ON ONE LINE - NO NEWLINES
- Example: [call:default_api:read_file]{"filePath":"/path/to/file"}[/call]
- Then CLOSE with [/call]
- Respond with NOTHING else if you are calling a tool"""


# ============================================================
# Parsed Tool Call
# ============================================================

class ParsedToolCall:
    """Represents a parsed tool call from model output"""

    def __init__(
        self,
        index: int,
        name: str,
        arguments: str,
        raw_text: Optional[str] = None,
    ):
        self.index = index
        self.id = f"call_{int(time.time() * 1000)}_{index}"
        self.type = "function"
        self.name = name
        self.arguments = arguments
        self.raw_text = raw_text

    def to_dict(self) -> dict:
        """Convert to OpenAI tool_calls format"""
        return {
            "index": self.index,
            "id": self.id,
            "type": self.type,
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


# ============================================================
# JSON Parsing Utilities
# ============================================================

def _extract_balanced_json(s: str) -> Optional[str]:
    """
    Extract a balanced JSON object string starting from the first '{'.
    Handles nested braces, strings, and escape characters.
    """
    start_idx = s.find("{")
    if start_idx == -1:
        return None

    depth = 0
    in_string = False
    is_escaped = False

    for i in range(start_idx, len(s)):
        char = s[i]

        if char == "\\" and not is_escaped:
            is_escaped = True
            continue

        if char == '"' and not is_escaped:
            in_string = not in_string
        elif not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return s[start_idx : i + 1]

        is_escaped = False

    return None


def _try_parse_json(s: str) -> Optional[dict]:
    """
    Try to parse JSON with multiple fallback strategies.
    Returns parsed dict or None if all attempts fail.
    """
    if not s:
        return None

    # Attempt 1: Direct parse
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 2: Fix unescaped newlines/tabs inside string values
    try:
        fixed = _fix_unescaped_control_chars(s)
        return json.loads(fixed)
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 3: Remove whitespace outside strings
    try:
        compact = _compact_json(s)
        return json.loads(compact)
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 4: Fix unquoted keys (Python dict style)
    try:
        double_quoted = s.replace("'", '"')
        return json.loads(double_quoted)
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 5: Fix missing quotes around keys
    try:
        fixed_keys = re.sub(
            r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:',
            r'\1"\2":',
            s,
        )
        compact = _compact_json(fixed_keys)
        return json.loads(compact)
    except (json.JSONDecodeError, ValueError):
        pass

    return None


def _fix_unescaped_control_chars(s: str) -> str:
    """Fix unescaped newlines and tabs inside JSON string values"""
    result = []
    in_string = False
    is_escaped = False

    for char in s:
        if char == "\\" and not is_escaped:
            is_escaped = True
            result.append(char)
        elif char == '"' and not is_escaped:
            in_string = not in_string
            result.append(char)
        elif in_string and char in ("\n", "\r", "\t"):
            if char == "\n":
                result.append("\\n")
            elif char == "\r":
                result.append("\\r")
            elif char == "\t":
                result.append("\\t")
        else:
            is_escaped = False
            result.append(char)

    return "".join(result)


def _compact_json(s: str) -> str:
    """Remove newlines and extra whitespace between JSON tokens"""
    result = []
    in_string = False
    is_escaped = False

    for char in s:
        if char == "\\" and not is_escaped:
            is_escaped = True
            result.append(char)
        elif char == '"' and not is_escaped:
            in_string = not in_string
            result.append(char)
        elif not in_string and char in ("\n", "\r", "\t"):
            continue
        else:
            is_escaped = False
            result.append(char)

    return "".join(result)


def _try_regex_fallback(s: str) -> Optional[dict]:
    """
    Regex fallback for specific known tools (write_to_file, replace_in_file).
    This is a last resort for completely broken JSON.
    """
    try:
        # Check if it looks like write_to_file
        if '"filePath"' in s and '"content"' in s:
            fp_match = re.search(r'"filePath"\s*:\s*"([^"]+)"', s)
            if fp_match:
                content_start = s.find('"content"')
                if content_start != -1:
                    value_start = s.find('"', content_start + 9) + 1
                    end_match = re.search(r'"\s*\}\s*(?:\[/call\])?\s*$', s)
                    if end_match:
                        value_end = end_match.start()
                        if value_start != 0 and value_end > value_start:
                            content_value = s[value_start:value_end]
                            return {
                                "filePath": fp_match.group(1),
                                "content": content_value.replace("\\n", "\n").replace('\\"', '"'),
                            }

        # Check if it looks like replace_in_file
        if '"filePath"' in s and '"old_str"' in s and '"new_str"' in s:
            fp_match = re.search(r'"filePath"\s*:\s*"([^"]+)"', s)
            if fp_match:
                old_str_start = s.find('"old_str"')
                new_str_start = s.find('"new_str"')
                if old_str_start != -1 and new_str_start != -1:
                    old_value_start = s.find('"', old_str_start + 9) + 1
                    old_value_end = s.rfind('"', 0, new_str_start)
                    new_value_start = s.find('"', new_str_start + 9) + 1
                    end_match = re.search(r'"\s*\}\s*(?:\[/call\])?\s*$', s)
                    if end_match:
                        new_value_end = end_match.start()
                        if (
                            old_value_start != 0
                            and old_value_end > old_value_start
                            and new_value_start != 0
                            and new_value_end > new_value_start
                        ):
                            old_str_val = s[old_value_start:old_value_end]
                            new_str_val = s[new_value_start:new_value_end]
                            return {
                                "filePath": fp_match.group(1),
                                "old_str": old_str_val.replace("\\n", "\n").replace('\\"', '"'),
                                "new_str": new_str_val.replace("\\n", "\n").replace('\\"', '"'),
                            }
    except Exception:
        pass

    return None


# ============================================================
# Main Parser
# ============================================================

def parse_tool_calls_from_text(
    text: str, model_type: str = "default"
) -> dict:
    """
    Parse tool calls from text content.

    Args:
        text: The model's output text
        model_type: Model type for parser selection ('kimi', 'glm', 'default', etc.)

    Returns:
        dict with 'content' (cleaned text) and 'tool_calls' (list of ParsedToolCall)
    """
    if not text:
        return {"content": "", "tool_calls": []}

    tool_calls = []
    clean_content = text

    # Check for function call markers
    has_function_calls = (
        "[function_calls]" in text
        or "function_calls]" in text
        or re.search(r"\[call[:=]", text) is not None
    )

    if not has_function_calls:
        return {"content": text, "tool_calls": []}

    # Prepend missing opening bracket if needed
    processed_text = text
    if "[function_calls]" not in processed_text:
        # Match function_calls] not preceded by [ or /
        missing_bracket_re = re.compile(r"(^|[^/\[])(function_calls\])")
        if missing_bracket_re.search(processed_text):
            processed_text = missing_bracket_re.sub(r"\1[\2", processed_text)
            print(f"[ToolParser] Prepended opening bracket")

    # Extract content inside [function_calls]...[/function_calls]
    # Also support unclosed blocks for streaming or malformed output
    block_re = re.compile(r"\[function_calls\]([\s\S]*?)(?:\[/function_calls\]|$)")
    block_idx = 0

    for block_match in block_re.finditer(processed_text):
        block_content = block_match.group(1)
        block_idx += 1

        # Parse individual [call:name]...[/call] inside the block
        if model_type in ("kimi", "glm", "minimax", "zai"):
            # Regex-based logic (proven for these models)
            if model_type == "minimax":
                call_re = re.compile(
                    r'\[(?:call\s*[:=]\s*([a-zA-Z0-9_:-]+)|invoke\s+name\s*=\s*"([a-zA-Z0-9_:-]+)")\]'
                    r"([\s\S]*?)\[/call\]"
                )
            else:
                call_re = re.compile(
                    r"\[call\s*[:=]?\s*([a-zA-Z0-9_:-]+)\]([\s\S]*?)\[/call\]"
                )

            for call_match in call_re.finditer(block_content):
                function_name = call_match.group(1) or call_match.group(2)
                if model_type == "minimax":
                    arguments_str = (call_match.group(3) or "").strip()
                else:
                    arguments_str = (call_match.group(2) or "").strip()

                # Clean up markdown code blocks
                if arguments_str.startswith("```") and arguments_str.endswith("```"):
                    arguments_str = re.sub(r"^```(?:json)?\s*", "", arguments_str, flags=re.IGNORECASE)
                    arguments_str = re.sub(r"\s*```$", "", arguments_str)

                parsed = _try_parse_json(arguments_str)
                if parsed:
                    tc = ParsedToolCall(
                        index=len(tool_calls),
                        name=function_name,
                        arguments=json.dumps(parsed, ensure_ascii=False),
                        raw_text=call_match.group(0),
                    )
                    tool_calls.append(tc)
        else:
            # Balanced-braces logic (for Qwen and other models with nested tags)
            call_start_re = re.compile(r"\[call[:=]?([a-zA-Z0-9_:-]+)\]")

            call_start_idx = 0
            while True:
                call_start_match = call_start_re.search(block_content, call_start_idx)
                if not call_start_match:
                    break

                function_name = call_start_match.group(1)
                args_start = call_start_match.end()
                remaining = block_content[args_start:]

                arguments_str = _extract_balanced_json(remaining)
                json_end_idx = -1
                parsed = None

                if arguments_str:
                    start_idx = remaining.find("{")
                    json_end_idx = start_idx + len(arguments_str)
                    clean_args = arguments_str.strip()
                    if clean_args.startswith("```") and clean_args.endswith("```"):
                        clean_args = re.sub(r"^```(?:json)?\s*", "", clean_args, flags=re.IGNORECASE)
                        clean_args = re.sub(r"\s*```$", "", clean_args)
                    parsed = _try_parse_json(clean_args)

                if not parsed:
                    parsed = _try_regex_fallback(remaining)
                    if parsed:
                        end_call_idx = remaining.find("[/call]")
                        json_end_idx = end_call_idx if end_call_idx != -1 else len(remaining)

                if parsed:
                    raw_text_end = args_start + json_end_idx
                    after_json = block_content[raw_text_end:]
                    close_tag_match = re.match(r"^\s*\[/call\]", after_json)
                    if close_tag_match:
                        raw_text_end += len(close_tag_match.group(0))

                    tc = ParsedToolCall(
                        index=len(tool_calls),
                        name=function_name,
                        arguments=json.dumps(parsed, ensure_ascii=False),
                        raw_text=block_content[call_start_match.start() : raw_text_end],
                    )
                    tool_calls.append(tc)
                    call_start_idx = raw_text_end
                else:
                    call_start_idx = call_start_match.end()

    # Remove parsed tool calls from content
    for tc in tool_calls:
        if tc.raw_text:
            clean_content = clean_content.replace(tc.raw_text, "")

    # Remove empty [function_calls]...[/function_calls] blocks
    clean_content = re.sub(
        r"\[function_calls\]\s*\[/function_calls\]", "", clean_content
    )

    return {
        "content": clean_content.strip(),
        "tool_calls": tool_calls,
    }
