"""本地 FastAPI 后端：向桌面前端提供多 API 流式对话、文件解析、皮肤与设置接口."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.database import Database
from app.desktop.bridge import DesktopBridge
from app.doc_parser import process_uploaded_file
from app.kimi_cli_bridge import (
    get_kimi_cli_models,
    get_kimi_cli_status,
    launch_kimi_terminal_action,
    list_kimi_cli_sessions,
    stream_kimi_cli_chat,
)
from app.llm_client import fetch_provider_models, stream_chat, test_provider_connection
from app.paths import get_uploads_dir, get_user_skins_dir, get_web_dir
from app.pet_care import PetCareEngine
from app.skins import (
    get_skin,
    import_single_image_skin,
    import_skin_from_zip,
    list_skins,
)
from app.updater import UpdateManager
from app.version import APP_VERSION, GITHUB_REPO_URL


class ProviderSaveBody(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    default_model: str | None = None
    models: list[str] | None = None


class ProviderTestBody(BaseModel):
    provider_id: str | None = None
    base_url: str = ""
    api_key: str | None = None
    model: str = ""


class ConversationCreateBody(BaseModel):
    title: str = "新对话"
    provider_id: str = ""
    model: str = ""
    persona_id: str = "assistant"
    mode: str = "work"  # work | chat
    project_dir: str = ""


class ConversationUpdateBody(BaseModel):
    title: str | None = None
    pinned: int | None = None
    provider_id: str | None = None
    model: str | None = None
    persona_id: str | None = None
    mode: str | None = None
    project_dir: str | None = None


class PersonaSaveBody(BaseModel):
    id: str | None = None
    name: str
    icon: str = "🎭"
    prompt: str


class ChatStreamBody(BaseModel):
    conversation_id: str | None = None
    content: str = ""
    attachments: list[dict[str, Any]] = []
    provider_id: str | None = None
    model: str | None = None
    persona_id: str | None = None
    mode: str | None = None  # chat | work
    memory_mode: str | None = None  # none | session | long_term
    project_dir: str | None = None
    permission_level: str | None = None
    web_search: bool = False
    thinking: bool = False
    reasoning_effort: str = "medium"
    regenerate_from_message_id: str | None = None


class WindowActionBody(BaseModel):
    action: str  # dialog | hide | toggle | screenshot | open_skins_dir | resize
    width: int | None = None
    height: int | None = None


class OpenCliSessionBody(BaseModel):
    session_id: str
    title: str = ""
    work_dir: str = ""


class CareRenameBody(BaseModel):
    name: str


@dataclass
class ActiveRun:
    """单个会话的独立后台运行上下文（与 SSE 连接解耦，切换项目/模式绝不中断）."""

    conv_id: str
    mode: str
    model: str
    started_at: float
    status_label: str = "正在连接..."
    steps: list[dict[str, Any]] = field(default_factory=list)
    content_parts: list[str] = field(default_factory=list)
    reasoning_parts: list[str] = field(default_factory=list)
    reasoning_seconds: float = 0.0
    sources: list[dict[str, Any]] = field(default_factory=list)
    user_message: dict[str, Any] | None = None
    assistant_message: dict[str, Any] | None = None
    done: bool = False
    stopped: bool = False
    had_error: bool = False
    task: asyncio.Task[None] | None = None
    subscribers: set[asyncio.Queue[dict[str, Any] | None]] = field(default_factory=set)

    def broadcast(self, event: dict[str, Any] | None) -> None:
        for q in list(self.subscribers):
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def snapshot(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conv_id,
            "mode": self.mode,
            "model": self.model,
            "started_at": self.started_at,
            "elapsed_sec": max(0, int(time.time() - self.started_at)),
            "status_label": self.status_label,
            "steps": [dict(s) for s in self.steps],
            "content": "".join(self.content_parts),
            "reasoning": "".join(self.reasoning_parts),
            "reasoning_seconds": self.reasoning_seconds,
            "sources": list(self.sources),
            "done": self.done,
            "stopped": self.stopped,
        }


def create_app(
    db: Database,
    bridge: DesktopBridge | None = None,
    care: PetCareEngine | None = None,
    port: int | None = None,
) -> FastAPI:
    app = FastAPI(title="YuiDesk Local Backend")
    care_engine = care or PetCareEngine()
    update_manager = UpdateManager()
    active_runs: dict[str, ActiveRun] = {}

    allowed_hosts = {"127.0.0.1", "localhost"}
    if port is None:
        # 仅在单元测试 TestClient 未指定端口时允许 testserver
        allowed_hosts.add("testserver")
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"^http://(127\.0\.0\.1|localhost)(:\d+)?$",
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )
    else:
        allowed_origins = [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def localhost_security_guard(request: Request, call_next):
        """防御 DNS Rebinding 与恶意网页跨站 CSRF：仅允许本机 127.0.0.1 / localhost 访问."""
        raw_host = (request.headers.get("host") or "").strip().lower()
        hostname = raw_host.split(":")[0] if raw_host else ""
        if hostname and hostname not in allowed_hosts:
            return JSONResponse({"detail": "Forbidden host"}, status_code=403)

        sec_fetch_site = (request.headers.get("sec-fetch-site") or "").strip().lower()
        if sec_fetch_site == "cross-site":
            return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)

        origin = (request.headers.get("origin") or "").strip()
        if origin:
            parsed_o = urlparse(origin)
            o_host = (parsed_o.hostname or "").lower()
            o_port = parsed_o.port
            if parsed_o.scheme != "http" or o_host not in ("127.0.0.1", "localhost"):
                return JSONResponse({"detail": "Forbidden origin"}, status_code=403)
            if port is not None and o_port != port:
                return JSONResponse({"detail": "Origin port mismatch"}, status_code=403)

        return await call_next(request)

    def _emit_pet_state(state: str, bubble: str = "") -> None:
        if bridge is not None:
            bridge.pet_state_changed.emit(state, bubble)

    def _has_other_active_runs(exclude_conv_id: str = "") -> bool:
        return any(
            cid != exclude_conv_id and not r.done
            for cid, r in active_runs.items()
        )

    async def _stop_run_by_id(conv_id: str) -> bool:
        run = active_runs.get(conv_id)
        if not run or run.done:
            return False
        run.stopped = True
        if run.task and not run.task.done():
            run.task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(run.task), timeout=2.5)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
        return True

    # ---------- Health & Bootstrap ----------

    @app.get("/api/bootstrap")
    def get_bootstrap() -> dict[str, Any]:
        settings = db.get_settings()
        # 实时同步本机 Kimi Code CLI config.toml 里的真实模型列表，避免选到不存在的模型名
        cli_models = get_kimi_cli_models()
        if len(cli_models) > 1:
            db.save_provider("kimi_cli", {"models": cli_models})
            if settings.get("active_provider_id") == "kimi_cli" and settings.get("active_model") not in cli_models:
                settings = db.update_settings({"active_model": "default"})
        providers = db.list_providers(include_raw_key=False)
        personas = db.list_personas()
        skins = list_skins()
        conversations = db.list_conversations()
        kimi_status = get_kimi_cli_status(settings.get("kimi_cli_path", ""))
        has_any_key = kimi_status["installed"] or any(
            p["has_api_key"] for p in providers if p["id"] not in ("ollama", "kimi_cli")
        )
        return {
            "app_version": APP_VERSION,
            "repo_url": GITHUB_REPO_URL,
            "settings": settings,
            "providers": providers,
            "personas": personas,
            "skins": skins,
            "conversations": conversations,
            "kimi_cli_status": kimi_status,
            "has_any_key": has_any_key,
            "active_runs": [r.snapshot() for r in active_runs.values() if not r.done],
        }

    @app.get("/api/kimi-cli/status")
    def api_kimi_cli_status(custom_path: str = "") -> dict[str, Any]:
        path = custom_path or db.get_settings().get("kimi_cli_path", "")
        return get_kimi_cli_status(path)

    @app.post("/api/kimi-cli/action/{action}")
    def api_kimi_cli_action(action: str) -> dict[str, Any]:
        path = db.get_settings().get("kimi_cli_path", "")
        return launch_kimi_terminal_action(action, path)

    # ---------- Settings ----------

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return db.get_settings()

    @app.post("/api/settings")
    def update_settings(updates: dict[str, Any]) -> dict[str, Any]:
        new_settings = db.update_settings(updates)
        if bridge is not None:
            bridge.pet_settings_changed.emit(new_settings)
        return new_settings

    # ---------- Providers ----------

    @app.get("/api/providers")
    def api_list_providers() -> list[dict[str, Any]]:
        return db.list_providers(include_raw_key=False)

    @app.post("/api/providers/{provider_id}")
    def api_save_provider(provider_id: str, body: ProviderSaveBody) -> dict[str, Any]:
        data = body.model_dump(exclude_unset=True)
        return db.save_provider(provider_id, data)

    @app.delete("/api/providers/{provider_id}")
    def api_delete_provider(provider_id: str) -> dict[str, Any]:
        ok = db.delete_provider(provider_id)
        return {"ok": ok}

    @app.post("/api/providers/test")
    async def api_test_provider(body: ProviderTestBody) -> dict[str, Any]:
        api_key = body.api_key
        base_url = body.base_url
        if body.provider_id:
            saved = db.get_provider(body.provider_id, include_raw_key=True)
            if saved:
                if not base_url:
                    base_url = saved["base_url"]
                if api_key is None:
                    api_key = saved.get("api_key", "")
        result = await test_provider_connection(base_url, api_key or "", body.model)
        if result.get("ok"):
            _emit_pet_state("happy", "连接测试成功啦！随时可以开聊~ ✨")
        else:
            _emit_pet_state("error", "连不上呢，检查一下 Key 或网络吧💦")
        return result

    @app.post("/api/providers/models")
    async def api_fetch_models(body: ProviderTestBody) -> dict[str, Any]:
        api_key = body.api_key
        base_url = body.base_url
        if body.provider_id:
            saved = db.get_provider(body.provider_id, include_raw_key=True)
            if saved:
                if not base_url:
                    base_url = saved["base_url"]
                if api_key is None:
                    api_key = saved.get("api_key", "")
        try:
            models = await fetch_provider_models(base_url, api_key or "")
            if body.provider_id and models:
                db.save_provider(body.provider_id, {"models": models})
            return {"ok": True, "models": models}
        except Exception as exc:
            return {"ok": False, "models": [], "message": str(exc)}

    # ---------- Personas ----------

    @app.get("/api/personas")
    def api_list_personas() -> list[dict[str, Any]]:
        return db.list_personas()

    @app.post("/api/personas")
    def api_save_persona(body: PersonaSaveBody) -> dict[str, Any]:
        return db.save_persona(body.model_dump())

    @app.delete("/api/personas/{persona_id}")
    def api_delete_persona(persona_id: str) -> dict[str, Any]:
        return {"ok": db.delete_persona(persona_id)}

    # ---------- Skins ----------

    @app.get("/api/skins")
    def api_list_skins() -> list[dict[str, Any]]:
        return list_skins()

    @app.post("/api/skins/import")
    async def api_import_skin(
        file: UploadFile = File(...),
        name: str = Form(""),
    ) -> dict[str, Any]:
        raw = await file.read()
        fname = file.filename or "skin"
        try:
            if fname.lower().endswith(".zip"):
                skin = import_skin_from_zip(raw, fname)
            else:
                skin = import_single_image_skin(raw, fname, skin_name=name)
            db.update_settings({"active_skin_id": skin["id"]})
            if bridge is not None:
                bridge.pet_settings_changed.emit(db.get_settings())
                bridge.pet_state_changed.emit("happy", f"换上「{skin['name']}」新衣服啦~ ✨")
            return {"ok": True, "skin": skin}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # ---------- Conversations & Messages ----------

    @app.get("/api/conversations")
    def api_list_conversations(q: str = "", mode: str = "") -> list[dict[str, Any]]:
        return db.list_conversations(query=q, mode=mode)

    @app.post("/api/conversations")
    def api_create_conversation(body: ConversationCreateBody) -> dict[str, Any]:
        settings = db.get_settings()
        eff_mode = "chat" if str(body.mode or settings.get("active_mode") or "work").lower() == "chat" else "work"
        eff_proj = "" if eff_mode == "chat" else (body.project_dir or settings.get("active_project_dir") or "")
        return db.create_conversation(
            title=body.title or ("新聊天" if eff_mode == "chat" else "新项目对话"),
            provider_id=body.provider_id or settings["active_provider_id"],
            model=body.model or settings["active_model"],
            persona_id=body.persona_id or settings["active_persona_id"],
            mode=eff_mode,
            project_dir=eff_proj,
        )

    @app.patch("/api/conversations/{conv_id}")
    def api_update_conversation(conv_id: str, body: ConversationUpdateBody) -> dict[str, Any]:
        updated = db.update_conversation(conv_id, body.model_dump(exclude_unset=True))
        if not updated:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return updated

    @app.delete("/api/conversations/{conv_id}")
    async def api_delete_conversation(conv_id: str) -> dict[str, Any]:
        await _stop_run_by_id(conv_id)
        return {"ok": db.delete_conversation(conv_id)}

    @app.delete("/api/conversations")
    async def api_clear_conversations(mode: str = "") -> dict[str, Any]:
        clean_mode = mode.strip().lower()
        for cid, run in list(active_runs.items()):
            if not clean_mode or run.mode == clean_mode:
                await _stop_run_by_id(cid)
        db.clear_all_conversations(mode=mode)
        return {"ok": True}

    @app.get("/api/conversations/{conv_id}/messages")
    def api_list_messages(conv_id: str) -> list[dict[str, Any]]:
        return db.list_messages(conv_id)

    @app.get("/api/conversations/{conv_id}/export")
    def api_export_conversation(conv_id: str) -> dict[str, Any]:
        conv = db.get_conversation(conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        msgs = db.list_messages(conv_id)
        lines = [f"# {conv['title']}\n"]
        for m in msgs:
            role_label = "用户" if m["role"] == "user" else f"助手 ({m.get('model') or 'AI'})"
            lines.append(f"## {role_label}\n")
            if m.get("reasoning"):
                lines.append(f"> **思考过程**\n>\n> " + m["reasoning"].replace("\n", "\n> ") + "\n")
            lines.append((m.get("content") or "") + "\n")
        return {"title": conv["title"], "markdown": "\n".join(lines)}

    # ---------- Uploads ----------

    @app.post("/api/upload")
    async def api_upload(
        file: UploadFile = File(...),
        provider_id: str = Form(""),
    ) -> dict[str, Any]:
        _emit_pet_state("reading", f"正在认真读《{file.filename}》...")
        raw = await file.read()
        settings = db.get_settings()
        pid = provider_id or settings["active_provider_id"]
        provider = db.get_provider(pid, include_raw_key=True)
        try:
            att = await process_uploaded_file(file.filename or "file.txt", raw, provider=provider)
            _emit_pet_state("happy", f"《{att['name']}》读完啦，快问我吧！")
            return {"ok": True, "attachment": att}
        except Exception as exc:
            _emit_pet_state("error", "文件解析失败了💦")
            raise HTTPException(status_code=400, detail=f"文件解析失败: {exc}")

    @app.get("/api/uploads/{filename}")
    def api_serve_upload(filename: str) -> FileResponse:
        safe = Path(filename).name
        target = get_uploads_dir() / safe
        if not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(target)

    # ---------- Chat & Work Streaming (Per-Conversation Concurrent Background Runs) ----------

    def _sse_pack(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def _execute_background_run(
        run: ActiveRun,
        *,
        provider: dict[str, Any],
        provider_id: str,
        model: str,
        body: ChatStreamBody,
        history: list[dict[str, Any]],
        conv_latest: dict[str, Any],
        system_prompt: str,
        eff_mode: str,
        eff_memory_mode: str,
        eff_long_memory: str,
        eff_project_dir: str,
        settings: dict[str, Any],
        fallback_search_provider: str,
        fallback_search_key: str,
        ai_timeout_sec: int,
    ) -> None:
        conv_id = run.conv_id
        reasoning_start: float | None = None

        run.broadcast(
            {
                "type": "meta",
                "conversation_id": conv_id,
                "mode": eff_mode,
                "memory_mode": eff_memory_mode,
                "started_at": run.started_at,
                "user_message": run.user_message,
            }
        )

        try:
            if provider_id == "kimi_cli":
                latest_text = body.content or (history[-1]["content"] if history else "")
                latest_atts = body.attachments or (history[-1].get("attachments", []) if history else [])
                sys_full = system_prompt
                if eff_long_memory:
                    mem_tag = "聊天长期记忆" if eff_mode == "chat" else "项目长期记忆"
                    sys_full = f"{sys_full}\n\n【{mem_tag}】\n{eff_long_memory}".strip()
                use_cli_session = "" if eff_memory_mode == "none" else str(conv_latest.get("cli_session_id") or "")
                stream_iter = stream_kimi_cli_chat(
                    prompt_text=latest_text,
                    attachments=latest_atts,
                    model=model,
                    system_prompt=sys_full,
                    cli_session_id=use_cli_session,
                    custom_path=str(settings.get("kimi_cli_path") or ""),
                    project_dir=eff_project_dir,
                    permission_level=str(body.permission_level or settings.get("permission_level") or "standard"),
                    mode=eff_mode,
                    thinking=bool(body.thinking),
                    reasoning_effort=str(body.reasoning_effort or "medium"),
                    timeout_sec=ai_timeout_sec,
                )
            else:
                eff_history = history[-1:] if eff_memory_mode == "none" else history
                stream_iter = stream_chat(
                    provider=provider,
                    model=model,
                    history=eff_history,
                    system_prompt=system_prompt,
                    user_memory=eff_long_memory,
                    web_search=body.web_search,
                    thinking=body.thinking,
                    reasoning_effort=body.reasoning_effort,
                    fallback_search_provider=fallback_search_provider,
                    fallback_search_key=fallback_search_key,
                )

            async for ev in stream_iter:
                ev_type = ev.get("type")
                if ev_type == "cli_session" and ev.get("session_id"):
                    if eff_memory_mode != "none":
                        db.update_conversation(conv_id, {"cli_session_id": ev["session_id"]})
                    continue

                if ev_type == "step_start":
                    step = {
                        "id": str(ev.get("id") or f"step_{len(run.steps) + 1}"),
                        "tool": str(ev.get("tool") or ""),
                        "title": str(ev.get("title") or "执行步骤"),
                        "status": "running",
                        "summary": "",
                        "ts": time.time(),
                    }
                    run.steps.append(step)
                    run.status_label = step["title"]
                    run.broadcast({"type": "step_start", "step": dict(step)})
                    continue

                if ev_type == "step_done":
                    tid = str(ev.get("id") or "")
                    ok = bool(ev.get("ok", True))
                    summary = str(ev.get("summary") or ("已完成" if ok else "执行异常"))
                    matched = None
                    if tid:
                        for s in reversed(run.steps):
                            if s.get("id") == tid:
                                matched = s
                                break
                    if matched is None:
                        for s in reversed(run.steps):
                            if s.get("status") == "running":
                                matched = s
                                break
                    if matched is not None:
                        matched["status"] = "done" if ok else "error"
                        matched["summary"] = summary
                        tid = str(matched["id"])
                    run.broadcast({"type": "step_done", "id": tid, "ok": ok, "summary": summary})
                    continue

                if ev_type == "step_note":
                    text = str(ev.get("text") or "").strip()
                    if text:
                        note_step = {
                            "id": f"note_{len(run.steps) + 1}",
                            "tool": "",
                            "title": text,
                            "status": "note",
                            "summary": "",
                            "ts": time.time(),
                        }
                        run.steps.append(note_step)
                        run.broadcast({"type": "step_note", "step": dict(note_step)})
                    continue

                if ev_type == "status":
                    run.status_label = str(ev.get("label") or run.status_label)
                    _emit_pet_state(ev.get("state", "thinking"), "")
                elif ev_type == "sources":
                    run.sources = ev.get("sources") or []
                elif ev_type == "reasoning":
                    if reasoning_start is None:
                        reasoning_start = time.perf_counter()
                    run.reasoning_parts.append(ev.get("delta", ""))
                elif ev_type == "content":
                    if reasoning_start is not None and run.reasoning_seconds == 0.0:
                        run.reasoning_seconds = round(time.perf_counter() - reasoning_start, 1)
                    run.status_label = "正在输出回复..."
                    run.content_parts.append(ev.get("delta", ""))
                elif ev_type == "error":
                    run.had_error = True
                    run.status_label = ""
                    _emit_pet_state("error", "呜哇，请求出错了")

                run.broadcast(ev)
                await asyncio.sleep(0)

        except asyncio.CancelledError:
            run.stopped = True
            run.status_label = ""
            for s in run.steps:
                if s.get("status") == "running":
                    s["status"] = "stopped"
                    s["summary"] = "已手动停止"
            run.broadcast({"type": "stopped", "message": "任务已手动停止"})
        except Exception as exc:
            run.had_error = True
            run.status_label = ""
            for s in run.steps:
                if s.get("status") == "running":
                    s["status"] = "error"
                    s["summary"] = "执行中断"
            _emit_pet_state("error", "处理出错了")
            run.broadcast({"type": "error", "message": f"本地服务异常：{exc}"})
        finally:
            for s in run.steps:
                if s.get("status") == "running":
                    s["status"] = "stopped" if run.stopped else ("error" if run.had_error else "done")
                    if not s.get("summary"):
                        s["summary"] = "已手动停止" if run.stopped else ("执行异常" if run.had_error else "已完成")

            final_content = "".join(run.content_parts)
            final_reasoning = "".join(run.reasoning_parts)
            if reasoning_start is not None and run.reasoning_seconds == 0.0:
                run.reasoning_seconds = round(time.perf_counter() - reasoning_start, 1)

            if run.stopped:
                stop_note = "> 任务已手动停止"
                final_content = (final_content.rstrip() + "\n\n" + stop_note) if final_content.strip() else stop_note

            if final_content or final_reasoning or run.steps:
                # 若会话在此期间已被用户删除，避免外键报错
                if db.get_conversation(conv_id):
                    saved_msg = db.add_message(
                        conv_id=conv_id,
                        role="assistant",
                        content=final_content,
                        reasoning=final_reasoning,
                        reasoning_seconds=run.reasoning_seconds,
                        sources=run.sources,
                        steps=run.steps,
                        model=model,
                    )
                    run.assistant_message = saved_msg
                    run.broadcast({"type": "saved", "assistant_message": saved_msg})

            run.done = True
            if active_runs.get(conv_id) is run:
                active_runs.pop(conv_id, None)

            if not _has_other_active_runs(conv_id):
                if run.stopped:
                    _emit_pet_state("idle", "任务已停止")
                elif not run.had_error and (final_content or final_reasoning):
                    _emit_pet_state("happy", "")
                elif not run.had_error:
                    _emit_pet_state("idle", "")

            run.broadcast({"type": "run_end", "conversation_id": conv_id, "stopped": run.stopped, "had_error": run.had_error})
            run.broadcast(None)

    async def _run_stream(body: ChatStreamBody, forced_mode: str | None = None) -> StreamingResponse:
        settings = db.get_settings()
        provider_id = body.provider_id or settings["active_provider_id"]
        provider = db.get_provider(provider_id, include_raw_key=True)
        if not provider:
            raise HTTPException(status_code=400, detail="无效的供应商配置")

        raw_mode = forced_mode or body.mode or settings.get("active_mode") or "work"
        eff_mode = "chat" if str(raw_mode).lower() == "chat" else "work"
        eff_project_dir = (
            ""
            if eff_mode == "chat"
            else str(body.project_dir if body.project_dir is not None else settings.get("active_project_dir") or "")
        )

        model = body.model or settings["active_model"] or provider["default_model"]
        persona_id = body.persona_id or settings["active_persona_id"]

        conv_id = body.conversation_id
        existing_conv = db.get_conversation(conv_id) if conv_id else None
        # 如果传入的会话模式与当前模式不一致，自动另起对应模式的独立会话，严格区分聊天记录和项目记录
        if not existing_conv or (existing_conv.get("mode") or "work") != eff_mode:
            title_seed = (body.content or "").strip() or (
                body.attachments[0].get("name", "新对话") if body.attachments else ("新聊天" if eff_mode == "chat" else "新项目对话")
            )
            title = title_seed[:26] + ("..." if len(title_seed) > 26 else "")
            conv = db.create_conversation(
                title=title,
                provider_id=provider_id,
                model=model,
                persona_id=persona_id,
                mode=eff_mode,
                project_dir=eff_project_dir,
            )
            conv_id = conv["id"]
        else:
            conv = existing_conv
            if conv["title"] in ("新对话", "新聊天", "新项目对话") and body.content.strip():
                new_title = body.content.strip()[:26]
                db.update_conversation(
                    conv_id,
                    {"title": new_title, "provider_id": provider_id, "model": model, "project_dir": eff_project_dir},
                )
            else:
                db.update_conversation(
                    conv_id,
                    {"provider_id": provider_id, "model": model, "persona_id": persona_id, "project_dir": eff_project_dir},
                )

        if conv_id in active_runs and not active_runs[conv_id].done:
            raise HTTPException(status_code=409, detail="当前会话正在执行中，请等待完成或先点击停止")

        if body.regenerate_from_message_id:
            db.delete_messages_from(conv_id, body.regenerate_from_message_id)

        user_msg = None
        if body.content.strip() or body.attachments:
            saved_atts = []
            for att in body.attachments:
                clean = {k: v for k, v in att.items() if k != "data_url"}
                saved_atts.append(clean)
            user_msg = db.add_message(
                conv_id=conv_id,
                role="user",
                content=body.content,
                attachments=saved_atts,
                model=model,
            )

        history = db.list_messages(conv_id)
        conv_latest = db.get_conversation(conv_id) or {}
        personas = {p["id"]: p for p in db.list_personas()}
        system_prompt = personas.get(persona_id, {}).get("prompt", "")

        default_mem_mode = (
            settings.get("chat_memory_mode", "long_term")
            if eff_mode == "chat"
            else settings.get("work_memory_mode", "session")
        )
        eff_memory_mode = str(body.memory_mode or default_mem_mode or "session").lower()
        if eff_memory_mode not in ("none", "session", "long_term"):
            eff_memory_mode = "session"

        raw_mode_mem = (
            str(settings.get("chat_memory") or "")
            if eff_mode == "chat"
            else str(settings.get("work_memory") or "")
        ).strip()
        eff_long_memory = raw_mode_mem if eff_memory_mode == "long_term" else ""

        fallback_search_provider = settings.get("fallback_search_provider", "none")
        fallback_search_key = db.get_fallback_search_key()
        ai_timeout_sec = int(settings.get("ai_timeout_sec") or 180)

        run = ActiveRun(
            conv_id=conv_id,
            mode=eff_mode,
            model=model,
            started_at=time.time(),
            status_label="正在连接...",
            user_message=user_msg,
        )
        sub_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        run.subscribers.add(sub_queue)
        active_runs[conv_id] = run

        run.task = asyncio.create_task(
            _execute_background_run(
                run,
                provider=provider,
                provider_id=provider_id,
                model=model,
                body=body,
                history=history,
                conv_latest=conv_latest,
                system_prompt=system_prompt,
                eff_mode=eff_mode,
                eff_memory_mode=eff_memory_mode,
                eff_long_memory=eff_long_memory,
                eff_project_dir=eff_project_dir,
                settings=settings,
                fallback_search_provider=fallback_search_provider,
                fallback_search_key=fallback_search_key,
                ai_timeout_sec=ai_timeout_sec,
            )
        )

        async def subscriber_generator():
            try:
                while True:
                    ev = await sub_queue.get()
                    if ev is None:
                        break
                    yield _sse_pack(ev)
            finally:
                # 断开单个前端流仅移除订阅，绝不杀死后台运行中的任务！
                run.subscribers.discard(sub_queue)

        return StreamingResponse(
            subscriber_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/runs/active")
    def api_list_active_runs() -> dict[str, Any]:
        return {"runs": [r.snapshot() for r in active_runs.values() if not r.done]}

    @app.get("/api/runs/{conv_id}/stream")
    async def api_attach_run_stream(conv_id: str) -> StreamingResponse:
        run = active_runs.get(conv_id)

        async def attach_generator():
            if not run or run.done:
                yield _sse_pack({"type": "run_end", "conversation_id": conv_id, "already_finished": True})
                return
            sub_q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            run.subscribers.add(sub_q)
            try:
                yield _sse_pack({"type": "snapshot", **run.snapshot()})
                while True:
                    ev = await sub_q.get()
                    if ev is None:
                        break
                    yield _sse_pack(ev)
            finally:
                run.subscribers.discard(sub_q)

        return StreamingResponse(
            attach_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/runs/{conv_id}/stop")
    async def api_stop_run(conv_id: str) -> dict[str, Any]:
        stopped = await _stop_run_by_id(conv_id)
        return {"ok": True, "stopped": stopped, "message": "已停止任务" if stopped else "任务已结束"}

    @app.post("/api/chat")
    async def api_chat_mode(body: ChatStreamBody) -> StreamingResponse:
        return await _run_stream(body, forced_mode="chat")

    @app.post("/api/work")
    async def api_work_mode(body: ChatStreamBody) -> StreamingResponse:
        return await _run_stream(body, forced_mode="work")

    @app.post("/api/chat/stream")
    async def api_chat_stream(body: ChatStreamBody) -> StreamingResponse:
        return await _run_stream(body, forced_mode=body.mode)

    # ---------- Auto-Update API (SHA-256 Verified + China Mirror Fallback) ----------

    @app.get("/api/update/status")
    def api_update_status() -> dict[str, Any]:
        return update_manager.get_status()

    @app.post("/api/update/check")
    async def api_update_check() -> dict[str, Any]:
        return await asyncio.to_thread(update_manager.check_for_updates)

    @app.post("/api/update/download")
    def api_update_download() -> dict[str, Any]:
        return update_manager.start_download()

    @app.post("/api/update/apply")
    async def api_update_apply() -> dict[str, Any]:
        res = update_manager.apply_staged_update()
        if res.get("restarting") and bridge is not None:
            async def _delayed_quit() -> None:
                await asyncio.sleep(0.35)
                bridge.quit_requested.emit()

            asyncio.create_task(_delayed_quit())
        return res

    # ---------- Desktop Window Actions ----------

    @app.post("/api/pet/preview/{state_name}")
    def api_pet_preview(state_name: str) -> dict[str, Any]:
        skin = get_skin(db.get_settings().get("active_skin_id", "default_sprite"))
        state_labels = skin.get("state_labels") or {}
        bubble_map = {
            "idle": "待机呼吸与自然眨眼中",
            "hover": "你好呀，有什么需要帮忙吗",
            "thinking": "正在认真思考中",
            "searching": "正在联网检索资料",
            "reading": "正在阅读文档",
            "speaking": "正在组织回复",
            "happy": "任务完成啦",
            "drag": "哇，被拎起来了",
            "file_catch": "松手读取文件",
            "error": "连接好像出了点问题",
            "sleep": "稍微小憩一会儿",
            "peek_right": "偷偷扒在边缘看你",
            "peek_left": "偷偷扒在边缘看你",
            "pet_head": "嘿嘿，被摸头好舒服呀",
            "eat_cake": "最喜欢草莓蛋糕了",
            "practice_guitar": "认真练习吉他中",
            "study_desk": "专心做笔记学习中",
            "hungry": "肚子咕噜叫了，想吃点心",
            "stretch": "呼——伸个大懒腰",
            "walk_left": "在桌面上散散步",
            "walk_right": "在桌面上散散步",
            "sit_swing": "坐下来晃晃小腿",
            "music_dance": "戴着耳机听歌摇摆",
            "shy_blush": "呜哇，好害羞呀",
            "proud_pose": "哼哼，很厉害吧",
        }
        custom_label = state_labels.get(state_name)
        bubble = f"{custom_label}中~" if custom_label else bubble_map.get(state_name, "")
        _emit_pet_state(state_name, bubble)
        return {"ok": True, "state": state_name}

    # ---------- 独立桌宠养成系统 API（完全脱离 AI） ----------

    def _apply_skin_care_overrides(state: dict[str, Any]) -> dict[str, Any]:
        skin = get_skin(db.get_settings().get("active_skin_id", "default_sprite"))
        ov = skin.get("care_overrides") or {}
        state = dict(state)
        state["skin_id"] = skin.get("id", "default_sprite")
        state["shop_title"] = ov.get("shop_title") or "轻音部小卖部（购买后可随时从背包投喂或送礼）"
        state["action_labels"] = {
            k: v.get("name", "") for k, v in (ov.get("actions") or {}).items() if isinstance(v, dict)
        }
        item_ov = ov.get("items") or {}
        if item_ov and isinstance(state.get("shop"), list):
            new_shop = []
            for it in state["shop"]:
                it_copy = dict(it)
                if it["id"] in item_ov and item_ov[it["id"]].get("name"):
                    it_copy["name"] = item_ov[it["id"]]["name"]
                new_shop.append(it_copy)
            state["shop"] = new_shop
        return state

    @app.get("/api/care/state")
    def api_care_state() -> dict[str, Any]:
        return _apply_skin_care_overrides(care_engine.get_state())

    @app.post("/api/care/action/{action_id}")
    def api_care_action(action_id: str) -> dict[str, Any]:
        res = care_engine.perform_action(action_id)
        skin = get_skin(db.get_settings().get("active_skin_id", "default_sprite"))
        act_ov = ((skin.get("care_overrides") or {}).get("actions") or {}).get(action_id) or {}
        bubble = str(act_ov.get("bubble") or res.get("bubble") or "")
        if res.get("ok") and act_ov.get("name"):
            res["message"] = f"{act_ov['name']}完成"
        if res.get("state"):
            res["state"] = _apply_skin_care_overrides(res["state"])
        if bridge is not None and res.get("pet_state"):
            bridge.pet_timed_state_requested.emit(
                str(res["pet_state"]),
                bubble,
                float(res.get("duration") or 3.6),
            )
        return res

    @app.post("/api/care/buy/{item_id}")
    def api_care_buy(item_id: str) -> dict[str, Any]:
        res = care_engine.buy_item(item_id)
        if res.get("state"):
            res["state"] = _apply_skin_care_overrides(res["state"])
        return res

    @app.post("/api/care/use/{item_id}")
    def api_care_use(item_id: str) -> dict[str, Any]:
        res = care_engine.use_item(item_id)
        skin = get_skin(db.get_settings().get("active_skin_id", "default_sprite"))
        item_ov = ((skin.get("care_overrides") or {}).get("items") or {}).get(item_id) or {}
        bubble = str(item_ov.get("bubble") or res.get("bubble") or "")
        if res.get("state"):
            res["state"] = _apply_skin_care_overrides(res["state"])
        if bridge is not None and res.get("pet_state"):
            bridge.pet_timed_state_requested.emit(
                str(res["pet_state"]),
                bubble,
                float(res.get("duration") or 3.8),
            )
        return res

    @app.post("/api/care/quest/claim/{quest_id}")
    def api_care_claim_quest(quest_id: str) -> dict[str, Any]:
        res = care_engine.claim_quest(quest_id)
        if bridge is not None and res.get("pet_state"):
            bridge.pet_timed_state_requested.emit(
                str(res["pet_state"]),
                str(res.get("bubble") or ""),
                float(res.get("duration") or 3.4),
            )
        return res

    @app.post("/api/care/checkin")
    def api_care_checkin() -> dict[str, Any]:
        res = care_engine.daily_checkin()
        if bridge is not None and res.get("pet_state"):
            bridge.pet_timed_state_requested.emit(
                str(res["pet_state"]),
                str(res.get("bubble") or ""),
                float(res.get("duration") or 3.5),
            )
        return res

    @app.post("/api/care/rename")
    def api_care_rename(body: CareRenameBody) -> dict[str, Any]:
        return care_engine.rename_pet(body.name)

    @app.get("/api/kimi-cli/sessions")
    def api_kimi_cli_sessions() -> list[dict[str, Any]]:
        settings = db.get_settings()
        return list_kimi_cli_sessions(str(settings.get("kimi_cli_path") or ""), limit=20)

    @app.post("/api/kimi-cli/sessions/open")
    def api_open_kimi_cli_session(body: OpenCliSessionBody) -> dict[str, Any]:
        sid = body.session_id.strip()
        if not sid:
            raise HTTPException(status_code=400, detail="Missing session_id")
        # 若本地已有关联会话则直接复用，否则新建一条 work 记录绑定该 cli_session_id
        for c in db.list_conversations(mode="work"):
            if c.get("cli_session_id") == sid:
                return c
        settings = db.get_settings()
        conv = db.create_conversation(
            title=(body.title or "Kimi CLI 任务")[:30],
            provider_id="kimi_cli",
            model=settings.get("active_model") or "default",
            persona_id=settings.get("active_persona_id") or "assistant",
            mode="work",
            project_dir=body.work_dir or "",
        )
        updated = db.update_conversation(conv["id"], {"cli_session_id": sid})
        return updated or conv

    @app.post("/api/desktop/action")
    def api_desktop_action(body: WindowActionBody) -> dict[str, Any]:
        action = body.action
        if action == "resize" and bridge is not None:
            if body.width and body.height:
                bridge.dialog_size_requested.emit(int(body.width), int(body.height))
            elif body.height:
                bridge.dialog_height_requested.emit(int(body.height))
        elif action == "hide_care" and bridge is not None:
            bridge.care_window_requested.emit("hide")
        elif action == "toggle_care" and bridge is not None:
            bridge.care_window_requested.emit("toggle")
        elif action == "pick_project" and bridge is not None:
            bridge.pick_project_requested.emit()
        elif action == "screenshot" and bridge is not None:
            bridge.screenshot_requested.emit()
        elif action == "open_skins_dir":
            skins_dir = get_user_skins_dir()
            if os.name == "nt":
                os.startfile(str(skins_dir))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(skins_dir)])
        elif bridge is not None:
            bridge.window_mode_requested.emit(action)
        return {"ok": True}

    # ---------- Static Web Frontend ----------

    web_dir = get_web_dir()
    if web_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(web_dir / "index.html")

        @app.get("/care")
        def care_page() -> FileResponse:
            return FileResponse(web_dir / "care.html")

    return app
