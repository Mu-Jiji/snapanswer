import json
import threading

import httpx
import pytest

from snapanswer.config import LlmSettings
from snapanswer.llm import (
    LlmClient,
    LlmError,
    build_user_prompt,
    chat_endpoint,
)


def settings(**overrides) -> LlmSettings:
    values = {
        "base_url": "https://example.test/v1",
        "model": "test-model",
        "stream": True,
        "system_prompt": "system",
        "api_key_env": "TEST_KEY",
    }
    values.update(overrides)
    return LlmSettings(**values)


def test_chat_endpoint() -> None:
    assert chat_endpoint("https://api.test/v1/") == "https://api.test/v1/chat/completions"
    assert (
        chat_endpoint("https://api.test/v1/chat/completions")
        == "https://api.test/v1/chat/completions"
    )
    assert chat_endpoint("") == ""


def test_prompt_contains_question() -> None:
    prompt = build_user_prompt("  1+1=?  ")
    assert "1+1=?" in prompt
    assert "题目开始" in prompt


def test_non_streaming_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is False
        assert request.headers["authorization"] == "Bearer sk-test"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "答案：2"}}],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 4,
                    "total_tokens": 15,
                },
            },
        )

    client = LlmClient(settings(stream=False), "sk-test", transport=httpx.MockTransport(handler))
    result = client.complete("1+1=?")
    assert result.text == "答案：2"
    assert result.model == "test-model"
    assert result.usage is not None
    assert result.usage.prompt_tokens == 11
    assert result.usage.total_tokens == 15
    assert result.usage.source == "api"


def test_streaming_response_and_callback() -> None:
    body = (
        'data: {"choices":[{"delta":{"content":"答案："}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"2"}}]}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":9,"completion_tokens":2,'
        '"total_tokens":11}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream_options"] == {"include_usage": True}
        return httpx.Response(
            200,
            content=body.encode(),
            headers={"content-type": "text/event-stream"},
        )

    chunks: list[str] = []
    client = LlmClient(settings(), "sk-test", transport=httpx.MockTransport(handler))
    result = client.complete("1+1=?", on_delta=chunks.append)
    assert result.text == "答案：2"
    assert chunks == ["答案：", "2"]
    assert result.usage is not None
    assert result.usage.total_tokens == 11
    assert result.usage.source == "api"


def test_streaming_without_usage_uses_estimate() -> None:
    body = (
        'data: {"choices":[{"delta":{"content":"答案"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body.encode(),
            headers={"content-type": "text/event-stream"},
        )

    client = LlmClient(settings(), "sk-test", transport=httpx.MockTransport(handler))
    result = client.complete("题目", on_delta=lambda text: None)
    assert result.usage is not None
    assert result.usage.source == "estimated"
    assert result.usage.total_tokens > 0


def test_stream_options_rejected_retries_without_it() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        if calls == 1:
            assert "stream_options" in payload
            return httpx.Response(400, json={"error": {"message": "unknown field"}})
        assert "stream_options" not in payload
        body = 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(
            200,
            content=body.encode(),
            headers={"content-type": "text/event-stream"},
        )

    client = LlmClient(settings(), "sk-test", transport=httpx.MockTransport(handler))
    result = client.complete("题目", on_delta=lambda text: None)
    assert result.text == "ok"
    assert calls == 2


def test_missing_key_for_remote_endpoint() -> None:
    client = LlmClient(settings(), "")
    with pytest.raises(LlmError, match="API Key"):
        client.complete("题目")


def test_local_endpoint_allows_missing_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "本地回答"}}]}
        )

    client = LlmClient(
        settings(base_url="http://127.0.0.1:11434/v1", stream=False),
        "",
        transport=httpx.MockTransport(handler),
    )
    assert client.complete("题目").text == "本地回答"


def test_http_error_is_readable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    client = LlmClient(settings(stream=False), "bad", transport=httpx.MockTransport(handler))
    with pytest.raises(LlmError, match="API Key 无效") as exc:
        client.complete("题目")
    assert "invalid key" in str(exc.value)


def test_cancel_keeps_partial_text() -> None:
    body = (
        'data: {"choices":[{"delta":{"content":"部分"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"内容"}}]}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body.encode(),
            headers={"content-type": "text/event-stream"},
        )

    cancel = threading.Event()

    def on_delta(text: str) -> None:
        cancel.set()

    client = LlmClient(settings(), "sk-test", transport=httpx.MockTransport(handler))
    with pytest.raises(LlmError) as exc:
        client.complete("题目", on_delta=on_delta, cancel_event=cancel)
    assert exc.value.partial == "部分"
