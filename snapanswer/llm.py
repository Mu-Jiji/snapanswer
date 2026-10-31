"""OpenAI-compatible chat client used by both cloud and local model servers."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import LlmSettings, is_local_endpoint
from .usage import TokenUsage, estimate_usage, usage_from_payload

log = logging.getLogger(__name__)

DeltaCallback = Callable[[str], None]


class LlmError(RuntimeError):
    """A user-facing model request error, optionally carrying partial output."""

    def __init__(
        self,
        message: str,
        partial: str = "",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.partial = partial
        self.status_code = status_code


@dataclass
class ChatResult:
    text: str
    model: str
    elapsed_sec: float
    usage: TokenUsage | None = None


def chat_endpoint(base_url: str) -> str:
    """Turn a configured base URL into a chat-completions endpoint."""
    base = base_url.strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def build_user_prompt(question: str) -> str:
    return (
        "下面是从屏幕截图中 OCR 识别出的题目文本。识别结果可能有少量错字、"
        "断行或多余字符，请先理解题意再作答。\n\n"
        "===== 题目开始 =====\n"
        f"{question.strip()}\n"
        "===== 题目结束 ====="
    )


def build_messages(settings: LlmSettings, question: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": settings.system_prompt.strip()},
        {"role": "user", "content": build_user_prompt(question)},
    ]


class LlmClient:
    def __init__(
        self,
        settings: LlmSettings,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.api_key = api_key.strip()
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "SnapAnswer/0.1",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif not is_local_endpoint(self.settings.base_url):
            raise LlmError(
                "尚未配置 API Key。请在设置中填写，或设置环境变量 "
                f"{self.settings.api_key_env or 'DEEPSEEK_API_KEY'}。"
                "如果这是本地模型服务，可把 base_url 设为 localhost/内网地址。"
            )
        headers.update({str(k): str(v) for k, v in self.settings.headers.items()})
        return headers

    def _payload(self, question: str, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": build_messages(self.settings, question),
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "stream": stream,
        }
        if stream and self.settings.request_usage:
            payload["stream_options"] = {"include_usage": True}
        return payload

    def complete(
        self,
        question: str,
        *,
        on_delta: DeltaCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ChatResult:
        endpoint = chat_endpoint(self.settings.base_url)
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise LlmError("模型 base_url 配置无效，请填写 http(s) 地址")
        if not question.strip():
            raise LlmError("题目文本为空")
        headers = self._headers()
        timeout = httpx.Timeout(
            self.settings.timeout_sec,
            connect=min(15.0, self.settings.timeout_sec),
        )
        use_stream = bool(self.settings.stream and on_delta is not None)
        payload = self._payload(question, use_stream)
        started = time.perf_counter()

        usage: TokenUsage | None = None
        try:
            with httpx.Client(
                timeout=timeout,
                headers=headers,
                follow_redirects=True,
                transport=self._transport,
            ) as client:
                if use_stream:
                    try:
                        text, usage = self._request_stream(
                            client, endpoint, payload, on_delta, cancel_event
                        )
                    except LlmError as exc:
                        # A few compatible servers reject the optional usage
                        # extension.  Keep the answer working and fall back to
                        # local token estimation.
                        if (
                            self.settings.request_usage
                            and exc.status_code in {400, 422}
                            and "stream_options" in payload
                            and not exc.partial
                        ):
                            log.warning(
                                "Server rejected stream_options; retrying without usage"
                            )
                            payload.pop("stream_options", None)
                            text, usage = self._request_stream(
                                client, endpoint, payload, on_delta, cancel_event
                            )
                        else:
                            raise
                else:
                    text, usage = self._request_once(client, endpoint, payload)
        except LlmError:
            raise
        except httpx.ConnectError as exc:
            raise LlmError(
                f"无法连接模型服务：{endpoint}\n"
                "请检查网络、base_url；使用 Ollama 时请确认它已在运行。"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LlmError(f"模型请求超时（{self.settings.timeout_sec:.0f} 秒）") from exc
        except httpx.HTTPError as exc:
            raise LlmError(f"模型请求失败：{exc}") from exc

        text = text.strip()
        if not text:
            raise LlmError("模型返回了空内容，请检查模型名称或稍后重试")
        if usage is None:
            prompt_text = "\n".join(
                message["content"] for message in build_messages(self.settings, question)
            )
            usage = estimate_usage(prompt_text, text)
        return ChatResult(
            text=text,
            model=self.settings.model,
            elapsed_sec=time.perf_counter() - started,
            usage=usage.normalized(),
        )

    def _request_once(
        self, client: httpx.Client, endpoint: str, payload: dict[str, Any]
    ) -> tuple[str, TokenUsage | None]:
        response = client.post(endpoint, json=payload)
        self._raise_for_status(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise LlmError("模型返回的不是有效 JSON，请检查接口地址") from exc
        return _extract_message_text(data), usage_from_payload(data)

    def _request_stream(
        self,
        client: httpx.Client,
        endpoint: str,
        payload: dict[str, Any],
        on_delta: DeltaCallback | None,
        cancel_event: threading.Event | None,
    ) -> tuple[str, TokenUsage | None]:
        pieces: list[str] = []
        usage: TokenUsage | None = None
        with client.stream("POST", endpoint, json=payload) as response:
            if response.status_code >= 400:
                body = response.read().decode("utf-8", errors="replace")
                raise _http_error(response.status_code, body)
            for line in response.iter_lines():
                if cancel_event is not None and cancel_event.is_set():
                    raise LlmError("已取消本次请求", "".join(pieces))
                line = line.strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    data = line[5:].strip()
                elif line.startswith("{"):
                    data = line
                else:
                    continue
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    log.debug("Ignoring non-JSON stream line: %s", data[:200])
                    continue
                if isinstance(event, dict) and event.get("error"):
                    raise LlmError(_error_message(event), "".join(pieces))
                event_usage = usage_from_payload(event)
                if event_usage is not None:
                    usage = event_usage
                delta = _extract_delta_text(event)
                if delta:
                    pieces.append(delta)
                    if on_delta is not None:
                        on_delta(delta)
        return "".join(pieces), usage

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        body = response.text
        raise _http_error(response.status_code, body)


def _http_error(status_code: int, body: str) -> LlmError:
    message = body.strip()
    try:
        data = json.loads(body)
        message = _error_message(data) or message
    except (json.JSONDecodeError, TypeError):
        pass
    message = " ".join(message.split())[:400]
    if status_code in {401, 403}:
        hint = "API Key 无效或没有访问权限"
    elif status_code == 404:
        hint = "接口地址或模型名称不存在"
    elif status_code == 429:
        hint = "请求过于频繁或额度不足"
    elif status_code == 400:
        hint = "请求被模型服务拒绝（请检查模型名称和参数）"
    elif status_code >= 500:
        hint = "模型服务暂时不可用"
    else:
        hint = "模型请求失败"
    return LlmError(
        f"{hint}（HTTP {status_code}）\n{message}",
        status_code=status_code,
    )


def _error_message(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    if error:
        return str(error)
    detail = data.get("detail")
    if isinstance(detail, str):
        return detail
    message = data.get("message")
    return str(message) if message else ""


def _extract_message_text(data: Any) -> str:
    if not isinstance(data, dict):
        raise LlmError("模型响应结构无法识别")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlmError("模型响应中没有 choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise LlmError("模型响应结构无法识别")
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict)
            )
        # Some reasoning models expose only reasoning_content while streaming
        # is disabled; surface it rather than showing a blank answer.
        reasoning = message.get("reasoning_content")
        if isinstance(reasoning, str):
            return reasoning
    text = first.get("text")
    return text if isinstance(text, str) else ""


def _extract_delta_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict)
            )
    message = first.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    text = first.get("text")
    return text if isinstance(text, str) else ""
