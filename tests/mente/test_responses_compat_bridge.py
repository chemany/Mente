import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

from mente.executors.responses_compat_bridge import (
    _translate_responses_request_to_anthropic,
    _translate_responses_request_to_chat_completions,
    start_responses_compat_bridge,
)
from mente.executors.runtime_config import ModelRuntime


def _sse(event: str, payload: dict[str, object]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


@contextmanager
def _anthropic_message_server():
    captured: dict[str, object] = {}

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):  # noqa: A003
            return

        def do_POST(self):  # noqa: N802
            captured["path"] = self.path
            captured["headers"] = {
                str(key).lower(): value for key, value in self.headers.items()
            }
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length)
            captured["body"] = json.loads(body.decode("utf-8"))

            payload = b"".join(
                [
                    _sse(
                        "message_start",
                        {
                            "type": "message_start",
                            "message": {
                                "id": "msg_1",
                                "type": "message",
                                "role": "assistant",
                                "content": [],
                                "model": "mimo-v2.5-pro",
                                "stop_reason": None,
                                "stop_sequence": None,
                                "usage": {"input_tokens": 12, "output_tokens": 0},
                            },
                        },
                    ),
                    _sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {"type": "text", "text": ""},
                        },
                    ),
                    _sse(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": "我是 Mimo。"},
                        },
                    ),
                    _sse(
                        "content_block_stop",
                        {
                            "type": "content_block_stop",
                            "index": 0,
                        },
                    ),
                    _sse(
                        "message_delta",
                        {
                            "type": "message_delta",
                            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                            "usage": {"output_tokens": 6},
                        },
                    ),
                    _sse(
                        "message_stop",
                        {
                            "type": "message_stop",
                        },
                    ),
                ]
            )

            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", captured
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@contextmanager
def _anthropic_tool_use_server():
    captured: dict[str, object] = {}

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):  # noqa: A003
            return

        def do_POST(self):  # noqa: N802
            captured["path"] = self.path
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length)
            captured["body"] = json.loads(body.decode("utf-8"))

            payload = b"".join(
                [
                    _sse(
                        "message_start",
                        {
                            "type": "message_start",
                            "message": {
                                "id": "msg_tool_1",
                                "type": "message",
                                "role": "assistant",
                                "content": [],
                                "model": "mimo-v2.5-pro",
                                "stop_reason": None,
                                "stop_sequence": None,
                                "usage": {"input_tokens": 20, "output_tokens": 0},
                            },
                        },
                    ),
                    _sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {
                                "type": "tool_use",
                                "id": "toolu_1",
                                "name": "shell",
                                "input": {},
                            },
                        },
                    ),
                    _sse(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "input_json_delta", "partial_json": "{\"command\":\"pwd\"}"},
                        },
                    ),
                    _sse(
                        "content_block_stop",
                        {
                            "type": "content_block_stop",
                            "index": 0,
                        },
                    ),
                    _sse(
                        "message_delta",
                        {
                            "type": "message_delta",
                            "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                            "usage": {"output_tokens": 8},
                        },
                    ),
                    _sse(
                        "message_stop",
                        {
                            "type": "message_stop",
                        },
                    ),
                ]
            )

            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", captured
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_responses_compat_bridge_translates_anthropic_messages_to_responses_sse():
    request_payload = {
        "model": "mimo-v2.5-pro",
        "instructions": "You are concise.",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello，你是谁？"}],
            }
        ],
        "tools": [],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "stream": True,
        "include": [],
    }

    with _anthropic_message_server() as (downstream_base_url, captured):
        with start_responses_compat_bridge(
            model_runtime=ModelRuntime(
                model="mimo-v2.5-pro",
                provider="xiaomi",
                base_url=downstream_base_url,
                api_mode="anthropic_messages",
                source="mente_model_settings",
            ),
            api_key="sk-test-xiaomi",
        ) as bridge_base_url:
            response = httpx.post(
                f"{bridge_base_url}/responses",
                json=request_payload,
                timeout=10.0,
            )

    assert response.status_code == 200
    assert "event: response.created" in response.text
    assert "event: response.output_text.delta" in response.text
    assert "event: response.output_item.done" in response.text
    assert "我是 Mimo。" in response.text
    assert "event: response.completed" in response.text

    assert captured["path"] == "/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-test-xiaomi"
    assert captured["body"]["model"] == "mimo-v2.5-pro"
    assert captured["body"]["system"] == "You are concise."
    assert captured["body"]["messages"][0]["role"] == "user"
    assert "hello，你是谁？" in json.dumps(captured["body"]["messages"], ensure_ascii=False)


def test_responses_compat_bridge_translates_anthropic_tool_use_into_function_call():
    request_payload = {
        "model": "mimo-v2.5-pro",
        "instructions": "You are concise.",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "列出当前目录"}],
            }
        ],
        "tools": [
            {
                "type": "function",
                "name": "shell",
                "description": "Run a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            }
        ],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "stream": True,
        "include": [],
    }

    with _anthropic_tool_use_server() as (downstream_base_url, _captured):
        with start_responses_compat_bridge(
            model_runtime=ModelRuntime(
                model="mimo-v2.5-pro",
                provider="xiaomi",
                base_url=downstream_base_url,
                api_mode="anthropic_messages",
                source="mente_model_settings",
            ),
            api_key="sk-test-xiaomi",
        ) as bridge_base_url:
            response = httpx.post(
                f"{bridge_base_url}/responses",
                json=request_payload,
                timeout=10.0,
            )

    assert response.status_code == 200
    assert '"type": "function_call"' in response.text or '"type":"function_call"' in response.text
    assert '"call_id": "toolu_1"' in response.text or '"call_id":"toolu_1"' in response.text
    assert '"name": "shell"' in response.text or '"name":"shell"' in response.text
    assert '"end_turn": false' in response.text or '"end_turn":false' in response.text


def test_responses_compat_bridge_translates_prior_tool_turns_back_to_anthropic_messages():
    request_payload = {
        "model": "mimo-v2.5-pro",
        "instructions": "You are concise.",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "列出当前目录"}],
            },
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "shell",
                "arguments": "{\"command\":\"pwd\"}",
            },
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "/root/code/Mente\n",
            },
        ],
        "tools": [],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "stream": True,
        "include": [],
    }

    with _anthropic_message_server() as (downstream_base_url, captured):
        with start_responses_compat_bridge(
            model_runtime=ModelRuntime(
                model="mimo-v2.5-pro",
                provider="xiaomi",
                base_url=downstream_base_url,
                api_mode="anthropic_messages",
                source="mente_model_settings",
            ),
            api_key="sk-test-xiaomi",
        ) as bridge_base_url:
            response = httpx.post(
                f"{bridge_base_url}/responses",
                json=request_payload,
                timeout=10.0,
            )

    assert response.status_code == 200
    messages_json = json.dumps(captured["body"]["messages"], ensure_ascii=False)
    assert '"tool_use_id": "call_1"' in messages_json or '"tool_use_id":"call_1"' in messages_json
    assert '"name": "shell"' in messages_json or '"name":"shell"' in messages_json
    assert '"/root/code/Mente\\n"' in messages_json


def test_responses_compat_bridge_uses_anthropic_output_config_for_json_schema():
    request_payload = {
        "model": "mimo-v2.5-pro",
        "instructions": "Return structured JSON.",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "介绍你自己"}],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                    "additionalProperties": False,
                },
            }
        },
        "tools": [],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "stream": True,
        "include": [],
    }

    with _anthropic_message_server() as (downstream_base_url, captured):
        with start_responses_compat_bridge(
            model_runtime=ModelRuntime(
                model="mimo-v2.5-pro",
                provider="xiaomi",
                base_url=downstream_base_url,
                api_mode="anthropic_messages",
                source="mente_model_settings",
            ),
            api_key="sk-test-xiaomi",
        ) as bridge_base_url:
            response = httpx.post(
                f"{bridge_base_url}/responses",
                json=request_payload,
                timeout=10.0,
            )

    assert response.status_code == 200
    assert "output_format" not in captured["body"]
    assert captured["body"]["output_config"] == {
        "format": {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
        }
    }


def test_responses_compat_bridge_lifts_developer_messages_into_anthropic_system():
    request_payload = {
        "model": "mimo-v2.5-pro",
        "input": [
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "你是一个简洁的中文助手。"}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello，你是谁？"}],
            },
        ],
        "tools": [],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "stream": True,
        "include": [],
    }

    with _anthropic_message_server() as (downstream_base_url, captured):
        with start_responses_compat_bridge(
            model_runtime=ModelRuntime(
                model="mimo-v2.5-pro",
                provider="xiaomi",
                base_url=downstream_base_url,
                api_mode="anthropic_messages",
                source="mente_model_settings",
            ),
            api_key="sk-test-xiaomi",
        ) as bridge_base_url:
            response = httpx.post(
                f"{bridge_base_url}/responses",
                json=request_payload,
                timeout=10.0,
            )

    assert response.status_code == 200
    assert captured["body"]["system"] == "你是一个简洁的中文助手。"
    assert [message["role"] for message in captured["body"]["messages"]] == ["user"]
    assert "hello，你是谁？" in json.dumps(captured["body"]["messages"], ensure_ascii=False)


def test_translate_chat_completions_request_pads_reasoning_content_for_thinking_tool_replay():
    request = _translate_responses_request_to_chat_completions(
        {
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "列出当前目录"}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "shell",
                    "arguments": "{\"command\":\"pwd\"}",
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": "/root/code/Mente\n",
                },
            ]
        },
        model="deepseek-v3.1",
        provider="deepseek",
        base_url="https://api.deepseek.com/v1",
    )

    assistant_replay = request["messages"][1]
    assert assistant_replay["role"] == "assistant"
    assert assistant_replay["tool_calls"][0]["function"]["name"] == "shell"
    assert assistant_replay["reasoning_content"] == ""


def test_translate_chat_completions_request_pads_reasoning_content_for_xiaomi_mimo_tool_replay():
    request = _translate_responses_request_to_chat_completions(
        {
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "列出当前目录"}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "shell",
                    "arguments": "{\"command\":\"cat SKILL.md\"}",
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": "# skill instructions\n",
                },
            ]
        },
        model="mimo-v2.5-pro",
        provider="xiaomi",
        base_url="https://token-plan-cn.xiaomimimo.com/v1",
    )

    assistant_replay = request["messages"][1]
    assert assistant_replay["role"] == "assistant"
    assert assistant_replay["tool_calls"][0]["function"]["name"] == "shell"
    assert assistant_replay["reasoning_content"] == ""


def test_translate_chat_completions_request_reuses_reasoning_item_for_next_assistant_message():
    request = _translate_responses_request_to_chat_completions(
        {
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "列出当前目录"}],
                },
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "先确认技能说明，再决定下一步。"}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "shell",
                    "arguments": "{\"command\":\"cat SKILL.md\"}",
                },
            ]
        },
        model="moonshot-v1-8k-thinking",
        provider="moonshot",
        base_url="https://api.moonshot.ai/v1",
    )

    assistant_replay = request["messages"][1]
    assert assistant_replay["role"] == "assistant"
    assert assistant_replay["tool_calls"][0]["function"]["name"] == "shell"
    assert assistant_replay["reasoning_content"] == "先确认技能说明，再决定下一步。"


def test_translate_anthropic_request_preserves_reasoning_before_tool_replay():
    request = _translate_responses_request_to_anthropic(
        {
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "列出当前目录"}],
                },
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "先确认技能说明，再决定下一步。"}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "shell",
                    "arguments": "{\"command\":\"cat SKILL.md\"}",
                },
            ]
        },
        model="claude-3-7-sonnet-20250219",
    )

    assistant_replay = request["messages"][1]
    assert assistant_replay["role"] == "assistant"
    assert assistant_replay["content"][0] == {
        "type": "text",
        "text": "先确认技能说明，再决定下一步。",
    }
    assert assistant_replay["content"][1]["type"] == "tool_use"
    assert assistant_replay["content"][1]["name"] == "shell"


def test_translate_anthropic_request_pads_thinking_block_for_xiaomi_mimo_tool_replay():
    request = _translate_responses_request_to_anthropic(
        {
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "列出当前目录"}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "shell",
                    "arguments": "{\"command\":\"cat SKILL.md\"}",
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": "# skill instructions\n",
                },
            ]
        },
        model="mimo-v2.5-pro",
        provider="xiaomi",
        base_url="https://token-plan-cn.xiaomimimo.com/anthropic",
    )

    assistant_replay = request["messages"][1]
    assert assistant_replay["role"] == "assistant"
    assert assistant_replay["content"][0] == {
        "type": "thinking",
        "thinking": "",
    }
    assert assistant_replay["content"][1]["type"] == "tool_use"
    assert assistant_replay["content"][1]["name"] == "shell"
