from __future__ import annotations

import json
import re
from typing import Any

import httpx

JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)
THINK_BLOCK = re.compile(r"<think>[\s\S]*?</think>", re.I)


class LLMError(RuntimeError):
    pass


class OperationCancelled(RuntimeError):
    """User aborted a long-running model operation."""

    pass


async def _cancelled(is_cancelled) -> bool:
    if is_cancelled is None:
        return False
    flag = is_cancelled()
    if hasattr(flag, "__await__"):
        flag = await flag  # type: ignore[misc]
    return bool(flag)


async def ensure_not_cancelled(is_cancelled) -> None:
    if await _cancelled(is_cancelled):
        raise OperationCancelled("cancelled_by_user")


def strip_thinking(text: str) -> str:
    return THINK_BLOCK.sub("", text or "").strip()


def parse_json_value(text: str) -> Any:
    raw = strip_thinking(text)
    fenced = JSON_BLOCK.search(raw)
    if fenced:
        raw = fenced.group(1).strip()
    start_obj = raw.find("{")
    start_arr = raw.find("[")
    starts = [i for i in (start_obj, start_arr) if i >= 0]
    if not starts:
        raise LLMError("模型没有返回 JSON")
    start = min(starts)
    raw = raw[start:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # trim trailing junk after last brace/bracket
        for end in range(len(raw), 0, -1):
            try:
                return json.loads(raw[:end])
            except json.JSONDecodeError:
                continue
        raise LLMError("无法解析模型 JSON")


async def chat_completion(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.2,
    timeout: float = 600.0,
    extra: dict | None = None,
    is_cancelled=None,
) -> str:
    import asyncio

    url = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4096,
        "stream": False,
    }
    if extra:
        payload.update(extra)
    timeout = httpx.Timeout(timeout, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        await ensure_not_cancelled(is_cancelled)
        req_task = asyncio.create_task(client.post(url, json=payload))
        try:
            while True:
                done, _ = await asyncio.wait({req_task}, timeout=0.4)
                if req_task in done:
                    break
                if await _cancelled(is_cancelled):
                    req_task.cancel()
                    try:
                        await req_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    raise OperationCancelled("cancelled_by_user")
            try:
                resp = req_task.result()
            except httpx.HTTPError as exc:
                raise LLMError(f"无法连接模型 {base_url}: {type(exc).__name__}: {exc}") from exc
        except asyncio.CancelledError:
            req_task.cancel()
            raise
        if resp.status_code >= 400:
            raise LLMError(f"{base_url} {resp.status_code}: {resp.text[:400]}")
        data = resp.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"模型响应格式异常: {data!r}"[:400]) from exc


async def chat_json(
    messages: list[dict[str, str]],
    *,
    primary_base: str,
    primary_model: str,
    fallback_base: str,
    fallback_model: str,
    allow_fallback: bool,
    thinking: str = "medium",
    is_cancelled=None,
) -> tuple[Any, bool]:
    extra = {"chat_template_kwargs": {"reasoning_effort": thinking}}
    try:
        text = await chat_completion(
            base_url=primary_base,
            model=primary_model,
            messages=messages,
            extra=extra,
            is_cancelled=is_cancelled,
        )
        return parse_json_value(text), False
    except OperationCancelled:
        raise
    except LLMError:
        if not allow_fallback:
            raise
        text = await chat_completion(
            base_url=fallback_base,
            model=fallback_model,
            messages=messages,
            timeout=600.0,
            extra={"options": {"num_ctx": 8192}},
            is_cancelled=is_cancelled,
        )
        try:
            return parse_json_value(text), True
        except LLMError:
            fix = await chat_completion(
                base_url=fallback_base,
                model=fallback_model,
                messages=[
                    *messages,
                    {"role": "assistant", "content": text[:4000]},
                    {"role": "user", "content": "上面不是合法 JSON。只输出修正后的 JSON 对象，不要解释。"},
                ],
                timeout=600.0,
                is_cancelled=is_cancelled,
            )
            return parse_json_value(fix), True
