"""统一多 API 流式对话引擎：Kimi 原生联网/深度思考 + 全平台 OpenAI 兼容."""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

import httpx

from app.doc_parser import (
    detect_urls,
    fetch_webpage_text,
    load_attachment_text,
    load_image_data_url,
)


async def fetch_provider_models(base_url: str, api_key: str) -> list[str]:
    """调用 /models 接口拉取供应商最新可用模型列表."""
    url = f"{base_url.rstrip('/')}/models"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data") or []
        models = [item["id"] for item in data if isinstance(item, dict) and item.get("id")]
        models.sort()
        return models


async def test_provider_connection(base_url: str, api_key: str, model: str) -> dict[str, Any]:
    """测试 API 连通性与鉴权是否有效."""
    if not base_url:
        return {"ok": False, "message": "请先填写 Base URL"}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            if model:
                resp = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 8,
                    },
                )
            else:
                resp = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)

        latency_ms = int((time.perf_counter() - start) * 1000)
        if resp.status_code == 200:
            return {"ok": True, "latency_ms": latency_ms, "message": f"连接成功 ({latency_ms} ms)"}
        detail = _extract_error_message(resp)
        return {"ok": False, "latency_ms": latency_ms, "message": f"HTTP {resp.status_code}: {detail}"}
    except Exception as exc:
        return {"ok": False, "message": f"连接失败: {exc}"}


def _extract_error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err)
            if err:
                return str(err)
            if body.get("message"):
                return str(body["message"])
    except Exception:
        pass
    return resp.text[:300] or resp.reason_phrase


async def _fallback_web_search(
    query: str,
    provider_type: str,
    api_key: str,
) -> tuple[str, list[dict[str, str]]]:
    """当使用非 Kimi 模型时，可选调用 Tavily 或 Bocha 博查搜索作为联网兜底."""
    if not api_key or provider_type == "none":
        return "", []
    sources: list[dict[str, str]] = []
    snippets: list[str] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        if provider_type == "tavily":
            resp = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": query, "max_results": 5},
            )
            resp.raise_for_status()
            for idx, item in enumerate(resp.json().get("results", []), start=1):
                title = item.get("title", "")
                url = item.get("url", "")
                content = item.get("content", "")
                sources.append({"index": idx, "title": title, "url": url})
                snippets.append(f"[{idx}] {title} ({url})\n{content}")
        elif provider_type == "bocha":
            resp = await client.post(
                "https://api.bochaai.com/v1/web-search",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"query": query, "count": 5, "summary": True},
            )
            resp.raise_for_status()
            web_pages = resp.json().get("data", {}).get("webPages", {}).get("value", [])
            for idx, item in enumerate(web_pages, start=1):
                title = item.get("name", "")
                url = item.get("url", "")
                snippet = item.get("summary") or item.get("snippet", "")
                sources.append({"index": idx, "title": title, "url": url})
                snippets.append(f"[{idx}] {title} ({url})\n{snippet}")
    return "\n\n".join(snippets), sources


def _build_api_messages(
    history: list[dict[str, Any]],
    system_prompt: str,
    user_memory: str,
    extra_web_context: str = "",
) -> list[dict[str, Any]]:
    """将数据库历史消息构造为 OpenAI / Kimi 多模态消息列表."""
    sys_parts = [system_prompt.strip()] if system_prompt.strip() else []
    if user_memory.strip():
        sys_parts.append(f"【用户长期偏好记忆】\n{user_memory.strip()}")
    if extra_web_context.strip():
        sys_parts.append(
            "【以下为实时联网检索结果，请优先结合并在回答中以 [编号] 标注参考来源】\n"
            + extra_web_context.strip()
        )

    messages: list[dict[str, Any]] = []
    if sys_parts:
        messages.append({"role": "system", "content": "\n\n".join(sys_parts)})

    for msg in history:
        role = msg["role"]
        text = msg.get("content", "") or ""
        attachments = msg.get("attachments") or []

        if role != "user" or not attachments:
            messages.append({"role": role, "content": text})
            continue

        # 拼接文档正文
        doc_blocks: list[str] = []
        image_parts: list[dict[str, Any]] = []
        for att in attachments:
            if att.get("kind") == "document":
                doc_text = load_attachment_text(att)
                if doc_text.strip():
                    doc_blocks.append(
                        f"【附件文档：{att.get('name', '未命名')}】\n{doc_text}\n【附件结束】"
                    )
                else:
                    doc_blocks.append(
                        f"【附件文档：{att.get('name', '未命名')}】\n（该文档内容为空白，提取文字为 0 字。请如实告知用户这是空白文档，切勿编造内容。）\n【附件结束】"
                    )
            elif att.get("kind") == "image":
                data_url = load_image_data_url(att)
                if data_url:
                    image_parts.append(
                        {"type": "image_url", "image_url": {"url": data_url}}
                    )

        full_text = "\n\n".join(doc_blocks + ([text] if text else []))
        if image_parts:
            content_parts: list[dict[str, Any]] = []
            if full_text:
                content_parts.append({"type": "text", "text": full_text})
            content_parts.extend(image_parts)
            messages.append({"role": "user", "content": content_parts})
        else:
            messages.append({"role": "user", "content": full_text})

    return messages


def _extract_sources_from_text(text: str) -> list[dict[str, Any]]:
    urls = detect_urls(text)
    return [{"index": i + 1, "title": u, "url": u} for i, u in enumerate(urls)]


async def stream_chat(
    provider: dict[str, Any],
    model: str,
    history: list[dict[str, Any]],
    system_prompt: str,
    user_memory: str = "",
    web_search: bool = False,
    thinking: bool = False,
    reasoning_effort: str = "medium",
    fallback_search_provider: str = "none",
    fallback_search_key: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """
    核心流式事件生成器，统一输出前端可直接消费的事件：
    - {"type": "status", "state": "searching|reading|thinking|speaking", "label": "..."}
    - {"type": "sources", "sources": [...]}
    - {"type": "reasoning", "delta": "..."}
    - {"type": "content", "delta": "..."}
    - {"type": "done", "usage": {...}}
    - {"type": "error", "message": "..."}
    """
    base_url = (provider.get("base_url") or "").rstrip("/")
    api_key = provider.get("api_key") or ""
    if not base_url:
        yield {"type": "error", "message": "当前供应商尚未配置 Base URL，请前往设置页完善配置。"}
        return
    if not api_key and provider.get("id") != "ollama":
        yield {
            "type": "error",
            "message": f"尚未配置 {provider.get('name', '当前模型')} 的 API Key，请点击左下角「设置与 API」填入后再试。",
        }
        return

    latest_user_text = ""
    for m in reversed(history):
        if m["role"] == "user":
            latest_user_text = m.get("content", "") or ""
            break

    # 1. 自动识别用户消息里的网页 URL 并抓取正文（复刻 Kimi 链接直读）
    extra_contexts: list[str] = []
    collected_sources: list[dict[str, Any]] = []
    detected_urls = detect_urls(latest_user_text)
    if detected_urls:
        yield {"type": "status", "state": "reading", "label": f"正在读取 {len(detected_urls)} 个网页内容..."}
        for idx, u in enumerate(detected_urls, start=1):
            page = await fetch_webpage_text(u)
            if page.get("text"):
                collected_sources.append(
                    {"index": len(collected_sources) + 1, "title": page["title"], "url": u}
                )
                extra_contexts.append(
                    f"【网页正文：{page['title']} ({u})】\n{page['text']}"
                )

    # 2. 联网搜索：非 Kimi 供应商走外部搜索兜底；Kimi 走官方内置 $web_search 工具循环
    use_kimi_builtin_search = bool(web_search and provider.get("supports_web_search"))
    if web_search and not use_kimi_builtin_search and latest_user_text.strip():
        if fallback_search_provider != "none" and fallback_search_key:
            yield {"type": "status", "state": "searching", "label": "正在联网检索最新资料..."}
            try:
                search_text, search_sources = await _fallback_web_search(
                    latest_user_text, fallback_search_provider, fallback_search_key
                )
                if search_text:
                    extra_contexts.append(search_text)
                    collected_sources.extend(search_sources)
                    yield {"type": "sources", "sources": collected_sources}
            except Exception as exc:
                yield {"type": "status", "state": "thinking", "label": f"外部搜索未命中({exc})，直接推理中..."}

    if collected_sources:
        yield {"type": "sources", "sources": collected_sources}

    messages = _build_api_messages(
        history=history,
        system_prompt=system_prompt,
        user_memory=user_memory,
        extra_web_context="\n\n".join(extra_contexts),
    )

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # 思考模型自动选择提示（如开启思考且用户仍停留在非思考默认模型，透传 reasoning_effort）
    actual_model = model or provider.get("default_model") or ""
    if not actual_model:
        yield {"type": "error", "message": "未指定模型名称，请在顶部或设置中选择一个模型。"}
        return

    yield {"type": "status", "state": "thinking", "label": "正在思考中..."}

    # 支持 Kimi 内置 $web_search 多轮工具调用循环（最多 3 轮防死循环）
    max_tool_rounds = 3 if use_kimi_builtin_search else 1
    current_messages = list(messages)

    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0)) as client:
        for _round in range(max_tool_rounds):
            payload: dict[str, Any] = {
                "model": actual_model,
                "messages": current_messages,
                "stream": True,
            }
            if use_kimi_builtin_search:
                payload["tools"] = [
                    {
                        "type": "builtin_function",
                        "function": {"name": "$web_search"},
                    }
                ]
            if thinking and provider.get("supports_thinking"):
                # Kimi K3 / OpenAI 推理模型支持 reasoning_effort；DeepSeek-R1/K2-thinking 默认返回 reasoning_content
                if "kimi-k3" in actual_model or actual_model.startswith("o"):
                    payload["reasoning_effort"] = reasoning_effort

            tool_calls_acc: dict[int, dict[str, Any]] = {}
            finish_reason = None
            has_started_speaking = False
            usage_info: dict[str, Any] = {}

            try:
                async with client.stream(
                    "POST",
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as resp:
                    if resp.status_code != 200:
                        raw_err = await resp.aread()
                        resp._content = raw_err
                        err_msg = _extract_error_message(resp)
                        # 如果是因为模型不支持 builtin_function 或 reasoning_effort，做一次自动降级重试
                        if (
                            resp.status_code == 400
                            and _round == 0
                            and ("tools" in payload or "reasoning_effort" in payload)
                        ):
                            use_kimi_builtin_search = False
                            thinking = False
                            continue
                        yield {"type": "error", "message": f"模型接口报错 (HTTP {resp.status_code})：{err_msg}"}
                        return

                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        if chunk.get("usage"):
                            usage_info = chunk["usage"]

                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]

                        # 深度思考流（兼容 Kimi / DeepSeek / Qwen / OpenAI 字段）
                        reasoning_piece = (
                            delta.get("reasoning_content")
                            or delta.get("reasoning")
                            or ""
                        )
                        if reasoning_piece:
                            yield {"type": "reasoning", "delta": reasoning_piece}

                        # 正常正文流
                        content_piece = delta.get("content") or ""
                        if content_piece:
                            if not has_started_speaking:
                                has_started_speaking = True
                                yield {"type": "status", "state": "speaking", "label": "正在回复中..."}
                            yield {"type": "content", "delta": content_piece}

                        # Kimi 原生工具调用流（$web_search）
                        for tc in delta.get("tool_calls") or []:
                            idx = tc.get("index", 0)
                            entry = tool_calls_acc.setdefault(
                                idx,
                                {
                                    "id": tc.get("id") or f"call_{idx}",
                                    "type": tc.get("type") or "function",
                                    "function": {"name": "", "arguments": ""},
                                },
                            )
                            if tc.get("id"):
                                entry["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                entry["function"]["name"] += fn["name"]
                            if fn.get("arguments"):
                                entry["function"]["arguments"] += fn["arguments"]

            except httpx.TimeoutException:
                yield {"type": "error", "message": "请求超时，请检查网络连接或稍后重试。"}
                return
            except Exception as exc:
                yield {"type": "error", "message": f"请求异常：{exc}"}
                return

            # 若 Kimi 请求执行 $web_search，按照 Moonshot 官方约定原样回传 arguments 触发服务端搜索
            if finish_reason == "tool_calls" and tool_calls_acc:
                yield {"type": "status", "state": "searching", "label": "正在通过 Kimi 联网检索实时信息..."}
                ordered_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
                current_messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": ordered_calls,
                    }
                )
                for call in ordered_calls:
                    fn_name = call["function"]["name"]
                    fn_args_raw = call["function"]["arguments"] or "{}"
                    # 尝试从搜索参数里提取检索关键词展示给用户
                    try:
                        parsed_args = json.loads(fn_args_raw)
                        search_query = parsed_args.get("query") or parsed_args.get("search_query")
                        if search_query:
                            yield {
                                "type": "status",
                                "state": "searching",
                                "label": f"正在联网搜索：{search_query}",
                            }
                    except Exception:
                        pass
                    current_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "name": fn_name,
                            "content": fn_args_raw,
                        }
                    )
                continue

            yield {"type": "done", "usage": usage_info}
            return

    yield {"type": "done", "usage": {}}
