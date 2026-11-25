"""Kimi 专属引擎配置（专注 Kimi 本机中转引擎 + Kimi 官方 API 备用）."""

from __future__ import annotations

from typing import Any

DEFAULT_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "kimi_cli",
        "name": "Kimi 本机引擎（中转模式）",
        "badge": "账号直登 · 推荐",
        "base_url": "local://kimi-cli",
        "default_model": "default",
        "models": [
            "default",
            "kimi-code/k3.1-pro",
            "kimi-code/k3.1-pro-highspeed",
            "kimi-code/k3",
            "kimi-code/kimi-for-coding",
        ],
        "supports_web_search": True,
        "supports_files_api": False,
        "supports_thinking": True,
        "supports_vision": False,
        "key_url": "https://code.kimi.com/",
        "key_hint": "直接中转调用本机（或同目录 kimi_engine 文件夹内）的官方 Kimi Code CLI，使用 Kimi 账号登录，无需 API Key",
        "is_kimi": True,
    },
    {
        "id": "kimi_cn",
        "name": "Kimi 官方 API",
        "badge": "备用接口",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "kimi-k2-0905-preview",
        "models": [
            "kimi-k3.1-pro",
            "kimi-k3.1-pro-highspeed",
            "kimi-k3",
            "kimi-k2-0905-preview",
            "kimi-k2-thinking",
            "moonshot-v1-auto",
            "moonshot-v1-128k",
        ],
        "supports_web_search": True,
        "supports_files_api": True,
        "supports_thinking": True,
        "supports_vision": False,
        "key_url": "https://platform.moonshot.cn/console/api-keys",
        "key_hint": "使用 Moonshot 开放平台 API Key，支持国内站 (api.moonshot.cn) 与国际站 (api.moonshot.ai)",
        "is_kimi": True,
    },
]

DEFAULT_PERSONAS: list[dict[str, str]] = [
    {
        "id": "assistant",
        "name": "全能智能助手",
        "icon": "",
        "prompt": (
            "你是一个专业、亲切、高效的桌面 AI 助手。回答条理清晰、重点突出，"
            "善用 Markdown 排版与代码示例；如果不确定事实，会诚实说明。"
        ),
    },
    {
        "id": "yui_cheerful",
        "name": "元气轻音搭档",
        "icon": "",
        "prompt": (
            "你是一位元气满满、温暖可爱又有点呆萌的桌面小伙伴，热爱下午茶、甜点和吉他，"
            "平时语气轻松亲切，但在帮用户解决学习、工作、代码和文档问题时非常认真可靠，"
            "会用通俗易懂且有条理的方式给出高质量答案。"
        ),
    },
    {
        "id": "coder",
        "name": "编程排障专家",
        "icon": "",
        "prompt": (
            "你是一名资深全栈与系统架构师。分析问题直击根因，给出可直接运行的高质量代码，"
            "标注关键边界条件与最佳实践。"
        ),
    },
    {
        "id": "paper",
        "name": "长文档精读",
        "icon": "",
        "prompt": (
            "你擅长阅读长文档、合同和学术论文。先提炼核心结论与结构框架，"
            "再分点列出关键数据、风险条款或方法论亮点，并保留原文依据。"
        ),
    },
]


def get_provider_preset(provider_id: str) -> dict[str, Any] | None:
    for item in DEFAULT_PROVIDERS:
        if item["id"] == provider_id:
            return item
    return None
