"""
Stream Tool Handler Module - Handle tool calls in streaming responses

Strategy: Buffer content when [function_calls] marker is detected,
parse tool calls and emit them as tool_calls delta instead of text content.
"""

import json
import time
from typing import Optional
from dataclasses import dataclass, field

from .tool_parser import parse_tool_calls_from_text


# ============================================================
# Tool Call State
# ============================================================

@dataclass
class ToolCallState:
    """State tracking for tool call detection in streaming responses"""

    content_buffer: str = ""
    is_buffering_tool_call: bool = False
    tool_call_index: int = 0
    has_emitted_tool_call: bool = False


def create_tool_call_state() -> ToolCallState:
    """Create a new ToolCallState instance"""
    return ToolCallState()


# ============================================================
# Base Chunk Helper
# ============================================================

def create_base_chunk(
    chat_id: Optional[str], model: str, created: Optional[int] = None
) -> dict:
    """Create a base chunk structure for OpenAI-compatible responses"""
    return {
        "id": chat_id,
        "model": model,
        "object": "chat.completion.chunk",
        "created": created or int(time.time()),
    }


# ============================================================
# Stream Content Processor
# ============================================================

def process_stream_content(
    content: str,
    state: ToolCallState,
    base_chunk: dict,
    is_first_chunk: bool = False,
    model_type: str = "default",
) -> dict:
    """
    Process streaming content and detect/parse tool calls.

    Args:
        content: New content chunk from the stream
        state: ToolCallState for tracking buffering state
        base_chunk: Base chunk structure for response
        is_first_chunk: Whether this is the first content chunk
        model_type: Model type for parser selection

    Returns:
        dict with 'chunks' (list of SSE chunks to emit) and
        'should_flush' (whether to flush the buffer)
    """
    result = []
    marker = "[function_calls]"

    if not content:
        return {"chunks": result, "should_flush": False}

    state.content_buffer += content

    # If not already buffering, check for marker
    if not state.is_buffering_tool_call:
        marker_idx = state.content_buffer.find(marker)

        if marker_idx != -1:
            state.is_buffering_tool_call = True
            # Emit text before the marker
            if marker_idx > 0:
                text_before = state.content_buffer[:marker_idx]
                if not state.has_emitted_tool_call:
                    delta = {}
                    if is_first_chunk:
                        delta["role"] = "assistant"
                    delta["content"] = text_before
                    result.append({
                        **base_chunk,
                        "choices": [{
                            "index": 0,
                            "delta": delta,
                            "finish_reason": None,
                        }],
                    })
                state.content_buffer = state.content_buffer[marker_idx:]
        else:
            # Check for partial marker at end of buffer
            found_partial = False
            for i in range(len(state.content_buffer)):
                if state.content_buffer[i] == "[":
                    potential_marker = state.content_buffer[i:]
                    if marker.startswith(potential_marker):
                        state.is_buffering_tool_call = True
                        found_partial = True
                        if i > 0:
                            text_before = state.content_buffer[:i]
                            if not state.has_emitted_tool_call:
                                delta = {}
                                if is_first_chunk:
                                    delta["role"] = "assistant"
                                delta["content"] = text_before
                                result.append({
                                    **base_chunk,
                                    "choices": [{
                                        "index": 0,
                                        "delta": delta,
                                        "finish_reason": None,
                                    }],
                                })
                            state.content_buffer = potential_marker
                        break

            if found_partial:
                return {"chunks": result, "should_flush": False}

    # If buffering, try to parse tool calls
    if state.is_buffering_tool_call:
        has_full_marker = marker in state.content_buffer
        is_prefix = marker.startswith(state.content_buffer)

        # If buffer doesn't match marker anymore, emit as regular content
        if not has_full_marker and not is_prefix:
            state.is_buffering_tool_call = False
            if state.content_buffer and not state.has_emitted_tool_call:
                delta = {}
                if is_first_chunk:
                    delta["role"] = "assistant"
                delta["content"] = state.content_buffer
                result.append({
                    **base_chunk,
                    "choices": [{
                        "index": 0,
                        "delta": delta,
                        "finish_reason": None,
                    }],
                })
            state.content_buffer = ""
            return {"chunks": result, "should_flush": True}

        # Try to parse tool calls from buffer
        parsed = parse_tool_calls_from_text(state.content_buffer, model_type)
        tool_calls = parsed["tool_calls"]

        if tool_calls:
            for tc in tool_calls:
                tc.index = state.tool_call_index
                state.tool_call_index += 1

                tc_dict = tc.to_dict()
                # Remove raw_text from the dict (not part of OpenAI format)
                tc_dict.pop("raw_text", None)

                delta = {"tool_calls": [tc_dict]}
                if is_first_chunk:
                    delta["role"] = "assistant"

                result.append({
                    **base_chunk,
                    "choices": [{
                        "index": 0,
                        "delta": delta,
                        "finish_reason": None,
                    }],
                })

                if tc.raw_text:
                    state.content_buffer = state.content_buffer.replace(
                        tc.raw_text, ""
                    )

            state.has_emitted_tool_call = True

            # Check if we've seen the closing tag
            if "[/function_calls]" in state.content_buffer:
                state.is_buffering_tool_call = False
                state.content_buffer = state.content_buffer.replace(
                    "[/function_calls]", ""
                ).strip()
            else:
                state.is_buffering_tool_call = "[function_calls]" in state.content_buffer

            if not state.is_buffering_tool_call:
                state.content_buffer = ""

            return {"chunks": result, "should_flush": True}
        else:
            # No tool calls found yet, keep buffering
            # Safety: if buffer is too large, give up buffering
            if len(state.content_buffer) > 500000:
                state.is_buffering_tool_call = False
                if not state.has_emitted_tool_call:
                    delta = {}
                    if is_first_chunk:
                        delta["role"] = "assistant"
                    delta["content"] = state.content_buffer
                    result.append({
                        **base_chunk,
                        "choices": [{
                            "index": 0,
                            "delta": delta,
                            "finish_reason": None,
                        }],
                    })
                state.content_buffer = ""
                return {"chunks": result, "should_flush": True}
            return {"chunks": result, "should_flush": False}

    # Not buffering - emit regular content
    if state.content_buffer:
        if not state.has_emitted_tool_call:
            delta = {}
            if is_first_chunk:
                delta["role"] = "assistant"
            delta["content"] = state.content_buffer
            result.append({
                **base_chunk,
                "choices": [{
                    "index": 0,
                    "delta": delta,
                    "finish_reason": None,
                }],
            })
        state.content_buffer = ""

    return {"chunks": result, "should_flush": True}


def flush_tool_call_buffer(
    state: ToolCallState,
    base_chunk: dict,
    model_type: str = "default",
) -> list:
    """
    Flush any remaining content in the buffer at the end of stream.

    Args:
        state: ToolCallState with buffered content
        base_chunk: Base chunk structure for response
        model_type: Model type for parser selection

    Returns:
        List of chunks to emit
    """
    result = []

    if not state.content_buffer:
        return result

    parsed = parse_tool_calls_from_text(state.content_buffer, model_type)
    tool_calls = parsed["tool_calls"]
    clean_content = parsed["content"]

    if tool_calls:
        for tc in tool_calls:
            tc.index = state.tool_call_index
            state.tool_call_index += 1

            tc_dict = tc.to_dict()
            tc_dict.pop("raw_text", None)

            result.append({
                **base_chunk,
                "choices": [{
                    "index": 0,
                    "delta": {"tool_calls": [tc_dict]},
                    "finish_reason": None,
                }],
            })

        state.has_emitted_tool_call = True

        # Output remaining clean content after tool calls
        if clean_content and clean_content.strip():
            result.append({
                **base_chunk,
                "choices": [{
                    "index": 0,
                    "delta": {"content": clean_content},
                    "finish_reason": None,
                }],
            })
    else:
        if state.content_buffer and not state.has_emitted_tool_call:
            result.append({
                **base_chunk,
                "choices": [{
                    "index": 0,
                    "delta": {"content": state.content_buffer},
                    "finish_reason": None,
                }],
            })
        elif state.content_buffer and state.has_emitted_tool_call:
            print(
                f"[StreamToolHandler] Discarding remaining buffer "
                f"(tool calls were emitted): {state.content_buffer[:200]}..."
            )

    state.content_buffer = ""
    return result


def should_block_output(state: ToolCallState) -> bool:
    """Check if we should block normal content output (buffering potential tool call)"""
    return state.is_buffering_tool_call and not state.has_emitted_tool_call
