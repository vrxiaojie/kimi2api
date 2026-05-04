"""
Stream Handler Module
Handles streaming responses from Kimi's gRPC-Web API,
converting them to OpenAI-compatible SSE format.
"""

import json
import struct
import time
from typing import Optional, Generator, Callable

from .config import config


def unix_timestamp() -> int:
    return int(time.time())


def _parse_grpc_web_frames(data: bytes) -> list[bytes]:
    """Parse gRPC-Web frames: 1 byte flag + 4 bytes big-endian length + payload"""
    frames = []
    offset = 0
    while offset + 5 <= len(data):
        flag = data[offset]
        length = struct.unpack(">I", data[offset + 1 : offset + 5])[0]
        if offset + 5 + length > len(data):
            break
        payload = data[offset + 5 : offset + 5 + length]
        frames.append(payload)
        offset += 5 + length
    return frames


class KimiStreamHandler:
    """
    Handles streaming responses from Kimi's API,
    converting them to OpenAI-compatible SSE (Server-Sent Events) chunks.
    
    Kimi uses gRPC-Web framing with JSON messages that can contain:
    - Thinking/reasoning content (block.think)
    - Text content (block.text)
    - Multi-stage detection (thinking -> answer phases)
    - Error messages
    - Heartbeat messages (ignored)
    """

    def __init__(
        self,
        model: str = "kimi-k2.5",
        conversation_id: str = "",
        enable_thinking: bool = False,
    ):
        self.model = model
        self.conversation_id = conversation_id
        self.enable_thinking = enable_thinking

        # State tracking
        self.real_chat_id: Optional[str] = None
        self.last_message_id: Optional[str] = None
        self.has_error: bool = False
        self.current_phase: Optional[str] = None  # 'thinking' or 'answer'
        self.reasoning_buffer: str = ""

        # gRPC-Web frame buffer
        self._buffer: bytes = b""

    def get_conversation_id(self) -> Optional[str]:
        """Get the real conversation ID if available"""
        if self.real_chat_id:
            return self.real_chat_id
        if self.conversation_id and not self.conversation_id.startswith("kimi-"):
            return self.conversation_id
        return None

    def get_last_message_id(self) -> Optional[str]:
        return self.last_message_id

    def _detect_multi_stage(self, data: dict) -> Optional[str]:
        """Detect if the message belongs to thinking or answer stage"""
        stages = data.get("block", {}).get("multiStage", {}).get("stages")
        if not stages or not isinstance(stages, list) or len(stages) == 0:
            return None

        first_stage = stages[0]
        if first_stage.get("name") == "STAGE_NAME_THINKING":
            return "answer" if first_stage.get("status") == "completed" else "thinking"
        return None

    def _is_thinking_mask(self, mask: Optional[str]) -> bool:
        return bool(mask and "block.think" in mask)

    def _is_answer_mask(self, mask: Optional[str]) -> bool:
        return bool(mask and "block.text" in mask)

    def _extract_think_content(self, data: dict) -> Optional[str]:
        return (data.get("block") or {}).get("think", {}).get("content")

    def _extract_text_content(self, data: dict) -> Optional[str]:
        return (data.get("block") or {}).get("text", {}).get("content")

    def process_raw_bytes(self, raw_data: bytes, emit: Callable[[dict], None]) -> None:
        """
        Process raw bytes from the stream. Accumulates in buffer,
        parses gRPC-Web frames, and emits OpenAI-format SSE chunks via callback.
        """
        self._buffer += raw_data
        frames = _parse_grpc_web_frames(self._buffer)
        
        # Keep unprocessed bytes in buffer
        total_consumed = 0
        for frame in frames:
            total_consumed += 5 + len(frame)
            try:
                text = frame.decode("utf-8").strip()
                if text:
                    data = json.loads(text)
                    self._handle_message(data, emit)
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Skip invalid frames
                pass

        self._buffer = self._buffer[total_consumed:]

    def _handle_message(self, data: dict, emit: Callable[[dict], None]) -> None:
        """Handle a single Kimi protocol message"""
        created = unix_timestamp()

        # Skip heartbeat
        if data.get("heartbeat"):
            return

        # Extract real chat ID
        chat = data.get("chat")
        if chat and chat.get("id") and not self.real_chat_id:
            self.real_chat_id = chat["id"]
            print(f"[Stream] Extracted real chat_id: {self.real_chat_id}")

        # Extract last message ID
        message = data.get("message")
        if message and message.get("role") == "assistant" and message.get("id"):
            if not self.last_message_id:
                self.last_message_id = message["id"]
                print(f"[Stream] Extracted assistant message id: {self.last_message_id}")

        # Detect multi-stage phase
        phase = self._detect_multi_stage(data)
        if phase:
            self.current_phase = phase
            print(f"[Stream] Detected phase: {phase}")

        # Check for thinking/answer flags
        text_block = data.get("block", {}).get("text", {})
        if text_block.get("flags") == "thinking":
            self.current_phase = "thinking"
        elif text_block.get("flags") == "answer":
            self.current_phase = "answer"

        # Handle error
        if data.get("error"):
            self.has_error = True
            error_msg = data["error"].get("message", str(data["error"]))
            print(f"[Stream] API Error: {error_msg}")
            emit({
                "id": self.get_conversation_id(),
                "object": "chat.completion.chunk",
                "created": created,
                "model": self.model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": f"Error: {error_msg}"},
                    "finish_reason": None,
                }],
            })
            emit({
                "id": self.get_conversation_id(),
                "object": "chat.completion.chunk",
                "created": created,
                "model": self.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            })
            emit(None)  # Signal done
            return

        # Handle set/append operations
        op = data.get("op")
        if op in ("set", "append"):
            mask = data.get("mask", "")

            if self._is_thinking_mask(mask):
                content = self._extract_think_content(data)
                if content:
                    # Emit reasoning_content
                    self.reasoning_buffer += content
                    emit({
                        "id": self.get_conversation_id(),
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": self.model,
                        "choices": [{
                            "index": 0,
                            "delta": {"reasoning_content": content},
                            "finish_reason": None,
                        }],
                    })

            elif self._is_answer_mask(mask):
                content = self._extract_text_content(data)
                if content:
                    emit({
                        "id": self.get_conversation_id(),
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": self.model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": content},
                            "finish_reason": None,
                        }],
                    })

            elif text_block.get("content"):
                content = text_block["content"]
                if self.current_phase == "thinking":
                    self.reasoning_buffer += content
                    emit({
                        "id": self.get_conversation_id(),
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": self.model,
                        "choices": [{
                            "index": 0,
                            "delta": {"reasoning_content": content},
                            "finish_reason": None,
                        }],
                    })
                else:
                    emit({
                        "id": self.get_conversation_id(),
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": self.model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": content},
                            "finish_reason": None,
                        }],
                    })

        # Handle completion
        if data.get("done") is not None:
            emit({
                "id": self.get_conversation_id(),
                "object": "chat.completion.chunk",
                "created": created,
                "model": self.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            })
            emit(None)  # Signal DONE


def generate_sse_events(
    response,
    model: str = "kimi-k2.5",
    conversation_id: str = "",
    enable_thinking: bool = False,
) -> Generator[str, None, None]:
    """
    Generator that yields OpenAI-compatible SSE strings
    from a streaming Kimi API response.
    
    Usage:
        for chunk in generate_sse_events(response):
            yield chunk
    """
    handler = KimiStreamHandler(
        model=model,
        conversation_id=conversation_id,
        enable_thinking=enable_thinking,
    )

    sent_role = False

    def emit_chunk(chunk: Optional[dict]) -> None:
        nonlocal sent_role
        if chunk is None:
            return

        # Inject role on first content chunk
        if not sent_role and chunk.get("choices"):
            delta = chunk["choices"][0].get("delta", {})
            if "content" in delta or "reasoning_content" in delta:
                delta["role"] = "assistant"
                sent_role = True

        return chunk

    chunks = []
    def collector(chunk: Optional[dict]):
        if chunk is None:
            return
        chunks.append(chunk)

    # Read and process raw bytes
    for raw_bytes in response.iter_content(chunk_size=8192):
        if not raw_bytes:
            continue
        handler.process_raw_bytes(raw_bytes, collector)

    # Emit collected chunks as SSE
    for chunk in chunks:
        chunk_with_role = emit_chunk(chunk)
        if chunk_with_role:
            yield f"data: {json.dumps(chunk_with_role, ensure_ascii=False)}\n\n"

    yield "data: [DONE]\n\n"
