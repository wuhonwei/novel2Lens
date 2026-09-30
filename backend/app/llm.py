from __future__ import annotations

import json
import re
from typing import Any

import httpx

JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)
# Prefer closed think blocks; also drop unclosed leading <think>… noise before JSON.
THINK_BLOCK = re.compile(r"<think>[\s\S]*?</think>", re.I)
UNCLOSED_THINK = re.compile(r"<think>[\s\S]*?(?=\{|\[)", re.I)
TRAILING_COMMA = re.compile(r",\s*([}\]])")


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
    raw = THINK_BLOCK.sub("", text or "")
    raw = UNCLOSED_THINK.sub("", raw)
    return raw.strip()


def _extract_json_candidate(text: str) -> str:
    raw = strip_thinking(text)
    fenced = JSON_BLOCK.search(raw)
    if fenced:
        raw = fenced.group(1).strip()
    # Unclosed markdown fence: take everything after the opening ```json
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*([\s\S]*)", raw, re.I)
        if m:
            raw = m.group(1).strip()
            if raw.endswith("```"):
                raw = raw[:-3].strip()
    start_obj = raw.find("{")
    start_arr = raw.find("[")
    starts = [i for i in (start_obj, start_arr) if i >= 0]
    if not starts:
        raise LLMError("模型没有返回 JSON")
    return raw[min(starts) :]


def _loads_lenient(raw: str) -> Any:
    cleaned = TRAILING_COMMA.sub(r"\1", raw)
    return json.loads(cleaned)


def _close_truncated_json(raw: str) -> str | None:
    """Best-effort close of truncated JSON objects/arrays (common max_tokens cut)."""
    s = TRAILING_COMMA.sub(r"\1", raw).rstrip()
    # Drop a trailing incomplete string / token after last safe boundary.
    # Walk back to last complete value terminator.
    cut = s
    for end in range(len(s), max(0, len(s) - 8000), -1):
        frag = s[:end].rstrip()
        if not frag:
            continue
        # Prefer ending on complete scalar / structure boundary.
        if frag[-1] not in '"}]|0123456789truefalsnulTRUEFALSENUL':
            # keep searching
            pass
        stack: list[str] = []
        in_str = False
        esc = False
        ok = True
        for ch in frag:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]":
                if not stack or stack[-1] != ch:
                    ok = False
                    break
                stack.pop()
        if in_str or not ok:
            continue
        if not stack:
            try:
                _loads_lenient(frag)
                return frag
            except json.JSONDecodeError:
                continue
        candidate = frag.rstrip().rstrip(",")
        candidate += "".join(reversed(stack))
        try:
            _loads_lenient(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    # Fallback: trim to last complete top-level array element if shots-like.
    if '"shots"' in s:
        marker = s.find('"shots"')
        arr_start = s.find("[", marker)
        if arr_start > 0:
            # Find last complete object inside shots array.
            last_obj_end = s.rfind("}")
            while last_obj_end > arr_start:
                frag = s[: last_obj_end + 1].rstrip().rstrip(",") + "]}"
                # Ensure we opened {"shots": [
                prefix = s[:arr_start]
                if not prefix.rstrip().endswith(":"):
                    break
                candidate = prefix + s[arr_start : last_obj_end + 1].rstrip().rstrip(",") + "]}"
                # Balance outer braces roughly
                if candidate.count("{") > candidate.count("}"):
                    candidate += "}" * (candidate.count("{") - candidate.count("}"))
                try:
                    _loads_lenient(candidate)
                    return candidate
                except json.JSONDecodeError:
                    last_obj_end = s.rfind("}", 0, last_obj_end)
                    continue
    return None


def parse_json_value(text: str) -> Any:
    raw = _extract_json_candidate(text)
    try:
        return _loads_lenient(raw)
    except json.JSONDecodeError:
        pass
    # Trim trailing junk after last brace/bracket
    for end in range(len(raw), 0, -1):
        try:
            return _loads_lenient(raw[:end])
        except json.JSONDecodeError:
            continue
    closed = _close_truncated_json(raw)
    if closed is not None:
        try:
            return _loads_lenient(closed)
        except json.JSONDecodeError:
            pass
    raise LLMError("无法解析模型 JSON")


async def chat_completion(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.2,
    timeout: float = 600.0,
    max_tokens: int = 16384,
    extra: dict | None = None,
    is_cancelled=None,
) -> str:
    import asyncio

    url = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": int(max_tokens),
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
    repair_user = "上面不是合法 JSON。只输出修正后的完整 JSON 对象，不要解释，不要 markdown。"

    async def _complete_and_parse(
        *,
        base_url: str,
        model: str,
        msgs: list[dict[str, Any]],
        used_fallback: bool,
        timeout: float = 600.0,
        extra_body: dict | None = None,
    ) -> tuple[Any, bool]:
        text = await chat_completion(
            base_url=base_url,
            model=model,
            messages=msgs,
            timeout=timeout,
            extra=extra_body,
            is_cancelled=is_cancelled,
        )
        try:
            return parse_json_value(text), used_fallback
        except LLMError:
            fix = await chat_completion(
                base_url=base_url,
                model=model,
                messages=[
                    *msgs,
                    {"role": "assistant", "content": text[:12000]},
                    {"role": "user", "content": repair_user},
                ],
                timeout=timeout,
                extra=extra_body,
                is_cancelled=is_cancelled,
            )
            return parse_json_value(fix), used_fallback

    try:
        return await _complete_and_parse(
            base_url=primary_base,
            model=primary_model,
            msgs=list(messages),
            used_fallback=False,
            extra_body=extra,
        )
    except OperationCancelled:
        raise
    except LLMError:
        if not allow_fallback:
            raise
        return await _complete_and_parse(
            base_url=fallback_base,
            model=fallback_model,
            msgs=list(messages),
            used_fallback=True,
            timeout=600.0,
            extra_body={"options": {"num_ctx": 8192}},
        )
