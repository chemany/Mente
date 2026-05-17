"""Mente-owned local Responses compatibility bridge for non-Responses runtimes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import uuid

from anthropic import Anthropic
from openai import OpenAI

from mente.executors.runtime_config import ModelRuntime, RuntimeConfig

_DEFAULT_ANTHROPIC_MAX_TOKENS = 8192
_BRIDGE_PROVIDER_KEY = "mente_bridge"


class ResponsesCompatBridgeError(RuntimeError):
    """Raised when the local Responses compatibility bridge cannot serve a request."""


@contextmanager
def start_responses_compat_bridge(
    *,
    model_runtime: ModelRuntime,
    api_key: str | None,
) -> Iterator[str]:
    """Start one loopback Responses bridge and yield its `/v1` base URL."""

    server = _BridgeServer(
        ("127.0.0.1", 0),
        _BridgeRequestHandler,
        bridge=_ResponsesCompatBridge(
            model_runtime=model_runtime,
            api_key=api_key,
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def apply_responses_compat_bridge(
    runtime_config: RuntimeConfig,
    *,
    bridge_base_url: str,
) -> RuntimeConfig:
    """Project one non-Responses runtime into a local Responses-compatible provider."""

    codex_config = deepcopy(runtime_config.codex_config)
    codex_config.pop("openai_base_url", None)
    model_providers = codex_config.get("model_providers")
    if not isinstance(model_providers, dict):
        model_providers = {}
        codex_config["model_providers"] = model_providers
    model_providers[_BRIDGE_PROVIDER_KEY] = {
        "name": "Mente Responses Bridge",
        "base_url": bridge_base_url,
        "wire_api": "responses",
        "env_key": "MENTE_CODEX_API_KEY",
        "requires_openai_auth": False,
    }
    codex_config["model_provider"] = _BRIDGE_PROVIDER_KEY
    if runtime_config.model_runtime.model:
        codex_config["model"] = runtime_config.model_runtime.model

    return RuntimeConfig(
        runtime_home=runtime_config.runtime_home,
        runtime_home_is_default=runtime_config.runtime_home_is_default,
        ignore_user_config=runtime_config.ignore_user_config,
        ignore_rules=runtime_config.ignore_rules,
        sandbox=runtime_config.sandbox,
        approval_policy=runtime_config.approval_policy,
        skip_git_repo_check=runtime_config.skip_git_repo_check,
        color=runtime_config.color,
        model_runtime=runtime_config.model_runtime,
        codex_config=codex_config,
        profile_overrides=runtime_config.profile_overrides,
        subprocess_env=dict(runtime_config.subprocess_env),
    )


@dataclass
class _ResponsesCompatBridge:
    model_runtime: ModelRuntime
    api_key: str | None

    def handle_models(self) -> dict[str, object]:
        model_id = self.model_runtime.model or "unknown"
        return {
            "object": "list",
            "data": [
                {
                    "id": model_id,
                    "object": "model",
                }
            ],
        }

    def stream_responses(self, request_payload: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
        response_id = f"resp_{uuid.uuid4().hex}"
        events: list[tuple[str, dict[str, object]]] = [
            (
                "response.created",
                {
                    "type": "response.created",
                    "response": {"id": response_id},
                },
            )
        ]
        if self.model_runtime.api_mode == "anthropic_messages":
            return events + self._stream_anthropic(request_payload, response_id=response_id)
        if self.model_runtime.api_mode == "chat_completions":
            return events + self._stream_chat_completions(request_payload, response_id=response_id)
        raise ResponsesCompatBridgeError(
            f"unsupported_model_runtime:{self.model_runtime.api_mode}"
        )

    def _stream_anthropic(
        self,
        request_payload: dict[str, object],
        *,
        response_id: str,
    ) -> list[tuple[str, dict[str, object]]]:
        client = Anthropic(
            api_key=self.api_key or "mente-bridge",
            base_url=self.model_runtime.base_url,
            max_retries=0,
        )
        request = _translate_responses_request_to_anthropic(
            request_payload,
            model=self.model_runtime.model or _string_value(request_payload.get("model")) or "",
            provider=self.model_runtime.provider,
            base_url=self.model_runtime.base_url,
        )
        raw_stream = client.messages.create(stream=True, **request)
        assistant_message_id = f"msg_{uuid.uuid4().hex}"
        content_blocks: list[dict[str, object]] = []
        text_by_index: dict[int, list[str]] = {}
        tool_by_index: dict[int, dict[str, object]] = {}
        stop_reason: str | None = None
        usage: dict[str, object] | None = None

        for event in raw_stream:
            event_type = getattr(event, "type", None)
            if event_type == "message_start":
                message = getattr(event, "message", None)
                if message is not None:
                    assistant_message_id = getattr(message, "id", assistant_message_id)
                    usage = _anthropic_usage_payload(getattr(message, "usage", None))
                continue
            if event_type == "content_block_start":
                content_block = getattr(event, "content_block", None)
                index = int(getattr(event, "index"))
                if content_block is None:
                    continue
                if getattr(content_block, "type", None) == "text":
                    text_by_index[index] = []
                    content_blocks.append({"kind": "text", "index": index})
                elif getattr(content_block, "type", None) == "tool_use":
                    tool_by_index[index] = {
                        "call_id": getattr(content_block, "id"),
                        "name": getattr(content_block, "name"),
                        "input_chunks": [],
                        "input": getattr(content_block, "input", None) or {},
                    }
                    content_blocks.append({"kind": "tool_use", "index": index})
                continue
            if event_type == "content_block_delta":
                delta = getattr(event, "delta", None)
                index = int(getattr(event, "index"))
                if delta is None:
                    continue
                delta_type = getattr(delta, "type", None)
                if delta_type == "text_delta":
                    text = getattr(delta, "text", "")
                    text_by_index.setdefault(index, []).append(text)
                elif delta_type == "input_json_delta":
                    tool_by_index.setdefault(index, {"input_chunks": [], "input": {}})["input_chunks"].append(
                        getattr(delta, "partial_json", "")
                    )
                continue
            if event_type == "message_delta":
                delta = getattr(event, "delta", None)
                if delta is not None:
                    stop_reason = getattr(delta, "stop_reason", stop_reason)
                usage = _anthropic_usage_payload(getattr(event, "usage", None)) or usage

        events: list[tuple[str, dict[str, object]]] = []
        for block in content_blocks:
            if block["kind"] == "text":
                text = "".join(text_by_index.get(int(block["index"]), []))
                if not text:
                    continue
                events.append(
                    (
                        "response.output_text.delta",
                        {
                            "type": "response.output_text.delta",
                            "delta": text,
                        },
                    )
                )
                events.append(
                    (
                        "response.output_item.done",
                        {
                            "type": "response.output_item.done",
                            "item": {
                                "type": "message",
                                "id": assistant_message_id,
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": text}],
                            },
                        },
                    )
                )
                continue
            tool = tool_by_index.get(int(block["index"]))
            if tool is None:
                continue
            tool_input = tool.get("input")
            tool_chunks = "".join(str(chunk) for chunk in tool.get("input_chunks", []))
            if tool_chunks.strip():
                tool_input = json.loads(tool_chunks)
            events.append(
                (
                    "response.output_item.done",
                    {
                        "type": "response.output_item.done",
                        "item": {
                            "type": "function_call",
                            "call_id": tool["call_id"],
                            "name": tool["name"],
                            "arguments": json.dumps(tool_input, ensure_ascii=False, separators=(",", ":")),
                        },
                    },
                )
            )

        events.append(
            (
                "response.completed",
                {
                    "type": "response.completed",
                    "response": {
                        "id": response_id,
                        "usage": usage,
                        "end_turn": stop_reason != "tool_use",
                    },
                },
            )
        )
        return events

    def _stream_chat_completions(
        self,
        request_payload: dict[str, object],
        *,
        response_id: str,
    ) -> list[tuple[str, dict[str, object]]]:
        client = OpenAI(
            api_key=self.api_key or "mente-bridge",
            base_url=self.model_runtime.base_url,
            max_retries=0,
        )
        request = _translate_responses_request_to_chat_completions(
            request_payload,
            model=self.model_runtime.model or _string_value(request_payload.get("model")) or "",
            provider=self.model_runtime.provider,
            base_url=self.model_runtime.base_url,
        )
        stream = client.chat.completions.create(stream=True, **request)
        message_text: list[str] = []
        tool_calls: dict[int, dict[str, object]] = {}
        completion_id = response_id
        finish_reason: str | None = None
        usage: dict[str, object] | None = None

        for chunk in stream:
            completion_id = getattr(chunk, "id", completion_id) or completion_id
            usage = _openai_usage_payload(getattr(chunk, "usage", None)) or usage
            for choice in getattr(chunk, "choices", []):
                delta = getattr(choice, "delta", None)
                finish_reason = getattr(choice, "finish_reason", finish_reason)
                if delta is None:
                    continue
                if getattr(delta, "content", None):
                    message_text.append(delta.content)
                for tool_call in getattr(delta, "tool_calls", []) or []:
                    state = tool_calls.setdefault(
                        int(tool_call.index or 0),
                        {
                            "call_id": tool_call.id,
                            "name": "",
                            "arguments": [],
                        },
                    )
                    if tool_call.id:
                        state["call_id"] = tool_call.id
                    function = getattr(tool_call, "function", None)
                    if function is not None:
                        if getattr(function, "name", None):
                            state["name"] = function.name
                        if getattr(function, "arguments", None):
                            state["arguments"].append(function.arguments)

        events: list[tuple[str, dict[str, object]]] = []
        text = "".join(message_text)
        if text:
            events.append(
                (
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "delta": text,
                    },
                )
            )
            events.append(
                (
                    "response.output_item.done",
                    {
                        "type": "response.output_item.done",
                        "item": {
                            "type": "message",
                            "id": f"msg_{uuid.uuid4().hex}",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": text}],
                        },
                    },
                )
            )
        for index in sorted(tool_calls):
            tool = tool_calls[index]
            events.append(
                (
                    "response.output_item.done",
                    {
                        "type": "response.output_item.done",
                        "item": {
                            "type": "function_call",
                            "call_id": tool["call_id"],
                            "name": tool["name"],
                            "arguments": "".join(str(part) for part in tool["arguments"]),
                        },
                    },
                )
            )
        events.append(
            (
                "response.completed",
                {
                    "type": "response.completed",
                    "response": {
                        "id": completion_id,
                        "usage": usage,
                        "end_turn": finish_reason != "tool_calls",
                    },
                },
            )
        )
        return events


class _BridgeServer(ThreadingHTTPServer):
    def __init__(self, server_address, request_handler_class, *, bridge: _ResponsesCompatBridge):
        super().__init__(server_address, request_handler_class)
        self.bridge = bridge


class _BridgeRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A003
        return

    def do_GET(self):  # noqa: N802
        if self.path != "/v1/models":
            self._write_json(404, {"error": {"message": "not found"}})
            return
        self._write_json(200, self.server.bridge.handle_models())

    def do_POST(self):  # noqa: N802
        if self.path != "/v1/responses":
            self._write_json(404, {"error": {"message": "not found"}})
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
            events = self.server.bridge.stream_responses(payload)
            encoded = b"".join(_encode_sse(event, body) for event, body in events)
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            self.wfile.flush()
        except Exception as exc:  # noqa: BLE001
            error_event = _encode_sse(
                "response.failed",
                {
                    "type": "response.failed",
                    "response": {
                        "error": {
                            "type": "invalid_request",
                            "code": "responses_compat_bridge_error",
                            "message": f"{type(exc).__name__}: {exc}",
                        }
                    },
                },
            )
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.send_header("content-length", str(len(error_event)))
            self.end_headers()
            self.wfile.write(error_event)
            self.wfile.flush()

    def _write_json(self, status: int, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
        self.wfile.flush()


def _encode_sse(event: str, payload: dict[str, object]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def _translate_responses_request_to_anthropic(
    request_payload: dict[str, object],
    *,
    model: str,
    provider: str | None = None,
    base_url: str | None = None,
) -> dict[str, object]:
    messages, embedded_system = _responses_input_to_anthropic_request_parts(
        request_payload.get("input"),
        needs_reasoning_replay_block=_anthropic_replay_needs_reasoning_block(
            model=model,
            provider=provider,
            base_url=base_url,
        ),
    )
    request: dict[str, object] = {
        "model": model,
        "max_tokens": _DEFAULT_ANTHROPIC_MAX_TOKENS,
        "messages": messages,
    }
    system_parts = [
        part
        for part in (
            _string_value(request_payload.get("instructions")),
            embedded_system,
        )
        if part
    ]
    if system_parts:
        request["system"] = "\n\n".join(system_parts)
    tools = _responses_tools_to_anthropic(request_payload.get("tools"))
    if tools:
        request["tools"] = tools
    output_config = _responses_text_to_anthropic_output_config(request_payload.get("text"))
    if output_config is not None:
        request["output_config"] = output_config
    return request


def _translate_responses_request_to_chat_completions(
    request_payload: dict[str, object],
    *,
    model: str,
    provider: str | None = None,
    base_url: str | None = None,
) -> dict[str, object]:
    needs_reasoning_content = _chat_completions_replay_needs_reasoning_content(
        model=model,
        provider=provider,
        base_url=base_url,
    )
    request: dict[str, object] = {
        "model": model,
        "messages": _responses_input_to_chat_messages(
            request_payload.get("input"),
            instructions=_string_value(request_payload.get("instructions")),
            needs_reasoning_content=needs_reasoning_content,
        ),
        "stream_options": {"include_usage": True},
    }
    tools = _responses_tools_to_chat(request_payload.get("tools"))
    if tools:
        request["tools"] = tools
        request["tool_choice"] = request_payload.get("tool_choice") or "auto"
        request["parallel_tool_calls"] = bool(request_payload.get("parallel_tool_calls"))
    response_format = _responses_text_to_chat_response_format(request_payload.get("text"))
    if response_format is not None:
        request["response_format"] = response_format
    return request


def _responses_input_to_anthropic_request_parts(
    raw_input: object,
    *,
    needs_reasoning_replay_block: bool = False,
) -> tuple[list[dict[str, object]], str | None]:
    if not isinstance(raw_input, list):
        return [], None
    messages: list[dict[str, object]] = []
    system_parts: list[str] = []
    pending_reasoning_text: list[str] = []
    for item in raw_input:
        if not isinstance(item, dict):
            continue
        item_type = _string_value(item.get("type"))
        if item_type == "message":
            role = _string_value(item.get("role")) or "user"
            blocks = _responses_content_to_anthropic_blocks(item.get("content"))
            if not blocks:
                continue
            if role in {"developer", "system"}:
                text = _anthropic_blocks_to_text(blocks)
                if text:
                    system_parts.append(text)
                continue
            if role not in {"user", "assistant"}:
                role = "user"
            if role == "assistant":
                reasoning_block = _consume_pending_anthropic_reasoning_block(
                    pending_reasoning_text,
                    as_thinking=needs_reasoning_replay_block,
                    force_placeholder=needs_reasoning_replay_block,
                )
                if reasoning_block is not None:
                    blocks = [reasoning_block, *blocks]
            _append_anthropic_message(messages, role=role, blocks=blocks)
        elif item_type == "reasoning":
            reasoning_text = _responses_reasoning_item_to_text(item)
            if reasoning_text:
                pending_reasoning_text.append(reasoning_text)
        elif item_type in {"function_call", "custom_tool_call", "local_shell_call", "tool_search_call"}:
            block = _responses_item_to_anthropic_tool_use(item)
            if block is not None:
                reasoning_block = _consume_pending_anthropic_reasoning_block(
                    pending_reasoning_text,
                    as_thinking=needs_reasoning_replay_block,
                    force_placeholder=needs_reasoning_replay_block,
                )
                blocks = [block]
                if reasoning_block is not None:
                    blocks = [reasoning_block, *blocks]
                _append_anthropic_message(messages, role="assistant", blocks=blocks)
        elif item_type in {"function_call_output", "custom_tool_call_output", "tool_search_output"}:
            block = _responses_item_to_anthropic_tool_result(item)
            if block is not None:
                _append_anthropic_message(messages, role="user", blocks=[block])
    return messages, "\n\n".join(system_parts) if system_parts else None


def _append_anthropic_message(
    messages: list[dict[str, object]],
    *,
    role: str,
    blocks: list[dict[str, object]],
) -> None:
    if messages and messages[-1]["role"] == role:
        existing = messages[-1].setdefault("content", [])
        if isinstance(existing, list):
            existing.extend(blocks)
            return
    messages.append({"role": role, "content": list(blocks)})


def _responses_content_to_anthropic_blocks(raw_content: object) -> list[dict[str, object]]:
    if not isinstance(raw_content, list):
        return []
    blocks: list[dict[str, object]] = []
    for entry in raw_content:
        if not isinstance(entry, dict):
            continue
        entry_type = _string_value(entry.get("type"))
        if entry_type in {"input_text", "output_text"}:
            text = _string_value(entry.get("text"))
            if text:
                blocks.append({"type": "text", "text": text})
            continue
        if entry_type == "input_image":
            raise ResponsesCompatBridgeError("anthropic bridge does not support input_image yet")
    return blocks


def _anthropic_blocks_to_text(blocks: list[dict[str, object]]) -> str | None:
    texts = [
        _string_value(block.get("text"))
        for block in blocks
        if isinstance(block, dict) and _string_value(block.get("type")) == "text"
    ]
    joined = "\n\n".join(text for text in texts if text)
    return joined or None


def _consume_pending_anthropic_reasoning_block(
    pending_reasoning_text: list[str],
    *,
    as_thinking: bool = False,
    force_placeholder: bool = False,
) -> dict[str, object] | None:
    reasoning_text = _consume_pending_reasoning_content(pending_reasoning_text)
    if as_thinking:
        if reasoning_text or force_placeholder:
            return {
                "type": "thinking",
                "thinking": reasoning_text,
            }
        return None
    if not reasoning_text:
        return None
    return {
        "type": "text",
        "text": reasoning_text,
    }


def _anthropic_replay_needs_reasoning_block(
    *,
    model: str,
    provider: str | None,
    base_url: str | None,
) -> bool:
    normalized_model = (model or "").strip().lower()
    normalized_provider = (provider or "").strip().lower()
    normalized_base_url = (base_url or "").strip().lower()
    return (
        normalized_provider == "xiaomi"
        or "mimo" in normalized_model
        or "xiaomimimo.com" in normalized_base_url
    )


def _responses_item_to_anthropic_tool_use(item: dict[str, object]) -> dict[str, object] | None:
    item_type = _string_value(item.get("type"))
    if item_type == "function_call":
        arguments = _json_or_empty_object(item.get("arguments"))
        return {
            "type": "tool_use",
            "id": _string_value(item.get("call_id")) or f"call_{uuid.uuid4().hex}",
            "name": _string_value(item.get("name")) or "function_call",
            "input": arguments,
        }
    if item_type == "custom_tool_call":
        arguments = _json_or_wrapped_value(item.get("input"))
        return {
            "type": "tool_use",
            "id": _string_value(item.get("call_id")) or f"call_{uuid.uuid4().hex}",
            "name": _string_value(item.get("name")) or "custom_tool_call",
            "input": arguments,
        }
    if item_type == "local_shell_call":
        return {
            "type": "tool_use",
            "id": _string_value(item.get("call_id")) or f"call_{uuid.uuid4().hex}",
            "name": "local_shell_call",
            "input": item.get("action") if isinstance(item.get("action"), dict) else {},
        }
    if item_type == "tool_search_call":
        return {
            "type": "tool_use",
            "id": _string_value(item.get("call_id")) or f"call_{uuid.uuid4().hex}",
            "name": "tool_search_call",
            "input": item.get("arguments") if isinstance(item.get("arguments"), dict) else {},
        }
    return None


def _responses_item_to_anthropic_tool_result(item: dict[str, object]) -> dict[str, object] | None:
    call_id = _string_value(item.get("call_id"))
    if not call_id:
        return None
    output_text = _responses_tool_output_to_text(item.get("output"))
    return {
        "type": "tool_result",
        "tool_use_id": call_id,
        "content": output_text,
    }


def _responses_input_to_chat_messages(
    raw_input: object,
    *,
    instructions: str | None,
    needs_reasoning_content: bool = False,
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    pending_reasoning_content: list[str] = []
    if instructions:
        messages.append({"role": "system", "content": instructions})
    if not isinstance(raw_input, list):
        return messages
    for item in raw_input:
        if not isinstance(item, dict):
            continue
        item_type = _string_value(item.get("type"))
        if item_type == "message":
            role = _string_value(item.get("role")) or "user"
            content = _responses_content_to_chat_content(item.get("content"))
            if content:
                message = {"role": role, "content": content}
                if role == "assistant" and needs_reasoning_content:
                    message["reasoning_content"] = _consume_pending_reasoning_content(
                        pending_reasoning_content
                    )
                messages.append(message)
        elif item_type == "reasoning":
            reasoning_text = _responses_reasoning_item_to_text(item)
            if reasoning_text:
                pending_reasoning_content.append(reasoning_text)
        elif item_type in {"function_call", "custom_tool_call", "local_shell_call", "tool_search_call"}:
            tool_call = _responses_item_to_chat_tool_call(item)
            if tool_call is None:
                continue
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [tool_call],
            }
            if needs_reasoning_content:
                message["reasoning_content"] = _consume_pending_reasoning_content(
                    pending_reasoning_content
                )
            messages.append(message)
        elif item_type in {"function_call_output", "custom_tool_call_output", "tool_search_output"}:
            call_id = _string_value(item.get("call_id"))
            if not call_id:
                continue
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": _responses_tool_output_to_text(item.get("output")),
                }
            )
    return messages


def _responses_reasoning_item_to_text(item: dict[str, object]) -> str | None:
    texts: list[str] = []
    summary = item.get("summary")
    if isinstance(summary, list):
        for entry in summary:
            if not isinstance(entry, dict):
                continue
            text = _string_value(entry.get("text"))
            if text:
                texts.append(text)
    content = item.get("content")
    if isinstance(content, list):
        for entry in content:
            if not isinstance(entry, dict):
                continue
            text = _string_value(entry.get("text"))
            if text:
                texts.append(text)
    if not texts:
        return None
    return "\n".join(texts)


def _consume_pending_reasoning_content(pending_reasoning_content: list[str]) -> str:
    if not pending_reasoning_content:
        return ""
    reasoning_content = "\n".join(
        chunk.strip() for chunk in pending_reasoning_content if chunk.strip()
    ).strip()
    pending_reasoning_content.clear()
    return reasoning_content


def _chat_completions_replay_needs_reasoning_content(
    *,
    model: str,
    provider: str | None,
    base_url: str | None,
) -> bool:
    normalized_model = (model or "").strip().lower()
    normalized_provider = (provider or "").strip().lower()
    normalized_base_url = (base_url or "").strip().lower()
    return (
        normalized_provider
        in {
            "deepseek",
            "moonshot",
            "kimi",
            "kimi-coding",
            "kimi-coding-cn",
            "xiaomi",
        }
        or "deepseek" in normalized_model
        or "moonshot" in normalized_model
        or "kimi" in normalized_model
        or "mimo" in normalized_model
        or "api.deepseek.com" in normalized_base_url
        or "api.kimi.com" in normalized_base_url
        or "moonshot.ai" in normalized_base_url
        or "moonshot.cn" in normalized_base_url
        or "xiaomimimo.com" in normalized_base_url
    )


def _responses_content_to_chat_content(raw_content: object) -> str | list[dict[str, object]]:
    if not isinstance(raw_content, list):
        return ""
    parts: list[dict[str, object]] = []
    text_chunks: list[str] = []
    for entry in raw_content:
        if not isinstance(entry, dict):
            continue
        entry_type = _string_value(entry.get("type"))
        if entry_type in {"input_text", "output_text"}:
            text = _string_value(entry.get("text"))
            if text:
                text_chunks.append(text)
            continue
        if entry_type == "input_image":
            image_url = _string_value(entry.get("image_url"))
            if image_url:
                parts.append({"type": "image_url", "image_url": {"url": image_url}})
    if parts:
        if text_chunks:
            parts.insert(0, {"type": "text", "text": "".join(text_chunks)})
        return parts
    return "".join(text_chunks)


def _responses_item_to_chat_tool_call(item: dict[str, object]) -> dict[str, object] | None:
    call_id = _string_value(item.get("call_id")) or f"call_{uuid.uuid4().hex}"
    item_type = _string_value(item.get("type"))
    name: str | None = None
    arguments: object = {}
    if item_type == "function_call":
        name = _string_value(item.get("name")) or "function_call"
        arguments = item.get("arguments") or "{}"
    elif item_type == "custom_tool_call":
        name = _string_value(item.get("name")) or "custom_tool_call"
        arguments = item.get("input") or "{}"
    elif item_type == "local_shell_call":
        name = "local_shell_call"
        arguments = json.dumps(item.get("action") if isinstance(item.get("action"), dict) else {})
    elif item_type == "tool_search_call":
        name = "tool_search_call"
        arguments = json.dumps(item.get("arguments") if isinstance(item.get("arguments"), dict) else {})
    if name is None:
        return None
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": str(arguments),
        },
    }


def _responses_tools_to_anthropic(raw_tools: object) -> list[dict[str, object]]:
    if not isinstance(raw_tools, list):
        return []
    tools: list[dict[str, object]] = []
    for tool in raw_tools:
        if not isinstance(tool, dict):
            continue
        if _string_value(tool.get("type")) != "function":
            continue
        name = _string_value(tool.get("name"))
        if not name:
            continue
        tools.append(
            {
                "name": name,
                "description": _string_value(tool.get("description")) or "",
                "input_schema": tool.get("parameters") if isinstance(tool.get("parameters"), dict) else {"type": "object"},
            }
        )
    return tools


def _responses_tools_to_chat(raw_tools: object) -> list[dict[str, object]]:
    if not isinstance(raw_tools, list):
        return []
    tools: list[dict[str, object]] = []
    for tool in raw_tools:
        if not isinstance(tool, dict):
            continue
        if _string_value(tool.get("type")) != "function":
            continue
        name = _string_value(tool.get("name"))
        if not name:
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": _string_value(tool.get("description")) or "",
                    "parameters": tool.get("parameters") if isinstance(tool.get("parameters"), dict) else {"type": "object"},
                },
            }
        )
    return tools


def _responses_text_to_chat_response_format(raw_text: object) -> dict[str, object] | None:
    if not isinstance(raw_text, dict):
        return None
    raw_format = raw_text.get("format")
    if not isinstance(raw_format, dict):
        return None
    if _string_value(raw_format.get("type")) != "json_schema":
        return None
    schema = raw_format.get("schema")
    if not isinstance(schema, dict):
        return None
    return {
        "type": "json_schema",
        "json_schema": {
            "name": _string_value(raw_format.get("name")) or "structured_output",
            "schema": schema,
            "strict": bool(raw_format.get("strict")),
        },
    }


def _responses_text_to_anthropic_output_config(raw_text: object) -> dict[str, object] | None:
    if not isinstance(raw_text, dict):
        return None
    raw_format = raw_text.get("format")
    if not isinstance(raw_format, dict):
        return None
    if _string_value(raw_format.get("type")) != "json_schema":
        return None
    schema = raw_format.get("schema")
    if not isinstance(schema, dict):
        return None
    return {"format": {"type": "json_schema", "schema": schema}}


def _responses_tool_output_to_text(raw_output: object) -> str:
    if isinstance(raw_output, str):
        return raw_output
    if isinstance(raw_output, list):
        texts = [
            _string_value(item.get("text"))
            for item in raw_output
            if isinstance(item, dict) and _string_value(item.get("type")) in {"input_text", "output_text"}
        ]
        return "".join(text for text in texts if text)
    if isinstance(raw_output, dict):
        content = _string_value(raw_output.get("content"))
        if content:
            return content
    return json.dumps(raw_output, ensure_ascii=False) if raw_output is not None else ""


def _string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate or None


def _json_or_empty_object(value: object) -> dict[str, object]:
    if isinstance(value, str) and value.strip():
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    return {}


def _json_or_wrapped_value(value: object) -> dict[str, object]:
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"input": value}
        if isinstance(parsed, dict):
            return parsed
        return {"input": parsed}
    if isinstance(value, dict):
        return value
    return {}


def _anthropic_usage_payload(usage: object) -> dict[str, object] | None:
    if usage is None:
        return None
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": None,
        "output_tokens": output_tokens,
        "output_tokens_details": None,
        "total_tokens": input_tokens + output_tokens,
    }


def _openai_usage_payload(usage: object) -> dict[str, object] | None:
    if usage is None:
        return None
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    prompt_token_details = getattr(usage, "prompt_tokens_details", None)
    cached_tokens = int(getattr(prompt_token_details, "cached_tokens", 0) or 0)
    input_tokens_details = None
    if cached_tokens:
        input_tokens_details = {"cached_tokens": cached_tokens}
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": input_tokens_details,
        "output_tokens": output_tokens,
        "output_tokens_details": None,
        "total_tokens": int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0),
    }
