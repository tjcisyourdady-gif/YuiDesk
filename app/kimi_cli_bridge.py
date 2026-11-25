"""官方 Kimi Code CLI 本地引擎中转适配器（支持同目录打包 kimi_engine/ 或系统已安装 kimi）."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from app.doc_parser import load_attachment_text
from app.paths import get_app_dir, get_data_dir

KIMI_INSTALL_PS1 = "irm https://code.kimi.com/kimi-code/install.ps1 | iex"


def get_kimi_cli_models() -> list[str]:
    """仅从 ~/.kimi-code/config.toml 读取已配置的模型别名列表（不读取任何密钥字段）."""
    cfg_path = Path.home() / ".kimi-code" / "config.toml"
    models: list[str] = ["default"]
    if cfg_path.is_file():
        try:
            cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
            default_m = cfg.get("default_model")
            if isinstance(default_m, str) and default_m and default_m not in models:
                models.append(default_m)
            for k in (cfg.get("models") or {}).keys():
                if isinstance(k, str) and k and k not in models:
                    models.append(k)
        except Exception:
            pass
    return models


def _find_git_bash() -> str | None:
    app_dir = get_app_dir()
    for p in (
        app_dir / "kimi_engine" / "git_bash" / "usr" / "bin" / "bash.exe",
        app_dir / "kimi_engine" / "git_bash" / "bin" / "bash.exe",
        Path(r"C:\Program Files\Git\bin\bash.exe"),
        Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
        Path(r"C:\Program Files (x86)\Git\bin\bash.exe"),
    ):
        if p.is_file():
            return str(p)
    found = shutil.which("bash")
    return found if found else None


def find_kimi_executable(custom_path: str = "") -> str | None:
    """按优先级查找可用的 Kimi Code CLI：自定义路径 > 同目录 kimi_engine/ > 本机 PATH 与常见安装目录."""
    candidates: list[Path] = []
    if custom_path.strip():
        candidates.append(Path(custom_path.strip()))

    # 1. 同文件夹便携引擎目录（方便以后与 YuiDesk 一起打包分发）
    app_dir = get_app_dir()
    for name in ("kimi.exe", "kimi.cmd", "kimi.bat", "kimi"):
        candidates.append(app_dir / "kimi_engine" / name)
        candidates.append(app_dir / "kimi" / name)

    # 2. 本机常见安装位置
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    localappdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    for base in (
        home / ".kimi-code" / "bin",
        home / ".local" / "bin",
        appdata / "npm",
        localappdata / "Programs" / "kimi-code",
        localappdata / "kimi-code",
    ):
        for name in ("kimi.exe", "kimi.cmd", "kimi"):
            candidates.append(base / name)

    for c in candidates:
        if c.is_file():
            return str(c)

    # 3. 系统 PATH 查找
    for cmd in ("kimi", "kimi.exe", "kimi.cmd"):
        found = shutil.which(cmd)
        if found:
            return found
    return None


def list_kimi_cli_sessions(custom_path: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """通过官方 `kimi session list --all --json` 读取本机 Kimi Code CLI 工作会话列表."""
    exe = find_kimi_executable(custom_path)
    if not exe:
        return []
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        res = subprocess.run(
            [exe, "session", "list", "--all", "--json", "--limit", str(max(1, min(50, int(limit))))],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=creationflags,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return []
        raw = json.loads(res.stdout)
        if not isinstance(raw, list):
            return []
        items: list[dict[str, Any]] = []
        for s in raw:
            if not isinstance(s, dict) or not s.get("id"):
                continue
            wd = str(s.get("workDir") or "")
            folder = Path(wd).name if wd else "默认工作区"
            meta = s.get("metadata") if isinstance(s.get("metadata"), dict) else {}
            title = str(s.get("title") or meta.get("title") or "").strip()
            updated_ms = int(s.get("updatedAt") or s.get("createdAt") or 0)
            if not title:
                ts_str = time.strftime("%m-%d %H:%M", time.localtime(updated_ms / 1000.0)) if updated_ms else ""
                title = f"{folder} ({ts_str})" if ts_str else folder
            items.append(
                {
                    "session_id": str(s["id"]),
                    "title": title,
                    "work_dir": wd,
                    "folder": folder,
                    "updated_at": updated_ms / 1000.0 if updated_ms else 0.0,
                }
            )
        return items
    except Exception:
        return []


def get_kimi_cli_status(custom_path: str = "") -> dict[str, Any]:
    exe = find_kimi_executable(custom_path)
    bash_path = _find_git_bash() if os.name == "nt" else "/bin/bash"
    has_git_bash = bool(bash_path)
    if not exe:
        return {
            "installed": False,
            "has_git_bash": has_git_bash,
            "path": "",
            "version": "",
            "install_cmd": KIMI_INSTALL_PS1,
            "message": "未检测到本机 Kimi Code CLI，可点击下方按钮安装或将其放入 kimi_engine 文件夹。",
        }
    version = ""
    try:
        kwargs: dict[str, Any] = {"capture_output": True, "text": True, "timeout": 6}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        res = subprocess.run([exe, "--version"], **kwargs)
        version = (res.stdout or res.stderr or "").strip().splitlines()[0] if (res.stdout or res.stderr) else ""
    except Exception:
        version = ""
    if not has_git_bash:
        msg = (
            f"已找到引擎：{exe}" + (f" ({version})" if version else "")
            + "，但本机尚未安装 Git Bash（Kimi 引擎必需）。请点下方「安装 Git 运行环境」，或直接使用下方「方式二：API Key」。"
        )
    else:
        msg = f"已就绪：{exe}" + (f" ({version})" if version else "")
    return {
        "installed": True,
        "has_git_bash": has_git_bash,
        "path": exe,
        "version": version,
        "install_cmd": KIMI_INSTALL_PS1,
        "message": msg,
    }


def launch_kimi_terminal_action(action: str, custom_path: str = "") -> dict[str, Any]:
    """在可见 PowerShell 终端中协助用户完成官方安装、Git 环境安装或账号授权登录."""
    if os.name != "nt":
        return {"ok": False, "message": "仅支持 Windows 终端引导"}
    new_console = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    if action == "install_git":
        # 优先使用国内高速镜像（阿里云 npmmirror），彻底避免 github.com 超时 (0x80072ee2)
        cmd = (
            "Write-Host '正在从国内高速镜像下载 Git for Windows（无需翻墙）...' -ForegroundColor Cyan; "
            "$mirror = 'https://registry.npmmirror.com/-/binary/git-for-windows/'; "
            "try { "
            "  $vers = Invoke-RestMethod -Uri $mirror -TimeoutSec 15 | Where-Object { $_.name -match '^v2\\.' } | Sort-Object date -Descending; "
            "  $latest = $vers[0].url; "
            "  $files = Invoke-RestMethod -Uri $latest -TimeoutSec 15; "
            "  $exe = $files | Where-Object { $_.name -match '^Git-.*-64-bit\\.exe$' } | Select-Object -First 1; "
            "  $dst = Join-Path $env:TEMP $exe.name; "
            "  Write-Host ('下载地址: ' + $exe.url) -ForegroundColor Gray; "
            "  Invoke-WebRequest -Uri $exe.url -OutFile $dst -UseBasicParsing; "
            "  Write-Host '下载完成，正在启动静默安装...' -ForegroundColor Green; "
            "  Start-Process -FilePath $dst -ArgumentList '/VERYSILENT','/NORESTART' -Wait; "
            "  Write-Host ''; Write-Host '安装完成！请关闭本窗口，并在桌宠设置里点击「刷新检测」。' -ForegroundColor Green; "
            "} catch { "
            "  Write-Host ('镜像下载失败: ' + $_.Exception.Message) -ForegroundColor Red; "
            "  Write-Host '你也可直接用浏览器打开 https://registry.npmmirror.com/binary.html?path=git-for-windows/ 手动下载安装。' -ForegroundColor Yellow; "
            "}"
        )
        subprocess.Popen(["powershell", "-NoExit", "-Command", cmd], creationflags=new_console)
        return {"ok": True, "message": "已打开国内镜像 Git 安装窗口"}
    if action == "install":
        cmd = (
            f"Write-Host '正在安装官方 Kimi Code CLI...' -ForegroundColor Cyan; "
            f"{KIMI_INSTALL_PS1}; "
            f"Write-Host ''; Write-Host '安装完成后可直接点击「登录 Kimi 账号」完成授权。' -ForegroundColor Green"
        )
        subprocess.Popen(["powershell", "-NoExit", "-Command", cmd], creationflags=new_console)
        return {"ok": True, "message": "已打开安装终端窗口"}
    if action == "login":
        exe = find_kimi_executable(custom_path)
        if not exe:
            return {"ok": False, "message": "尚未安装 Kimi Code CLI，请先点击「一键安装 Kimi 引擎」"}
        bash_path = _find_git_bash()
        env_prefix = ""
        if bash_path:
            bash_dir = str(Path(bash_path).parent)
            env_prefix = f"$env:KIMI_SHELL_PATH='{bash_path}'; $env:PATH='{bash_dir};' + $env:PATH; "
        cmd = (
            f"{env_prefix}"
            f"Write-Host '正在启动 Kimi 官方登录（国内站 kimi.com），请在浏览器中完成授权...' -ForegroundColor Cyan; "
            f"& '{exe}' login --region mainland-cn; "
            f"Write-Host ''; Write-Host '只要上方出现 Logged in to managed:kimi-code. 即代表登录成功（退出时若出现英文提示可忽略），直接关闭本窗口即可在桌宠中对话。' -ForegroundColor Green"
        )
        subprocess.Popen(["powershell", "-NoExit", "-Command", cmd], creationflags=new_console)
        return {"ok": True, "message": "已打开 Kimi 授权登录窗口"}
    return {"ok": False, "message": "未知操作"}


PERMISSION_RULES: dict[str, str] = {
    "readonly": (
        "【权限等级：只读模式】严格禁止修改、新建、删除任何文件，也禁止执行会产生副作用或写盘的终端命令。"
        "你只能读取文件、分析代码/文档、回答问题或给出修改建议。"
    ),
    "standard": (
        "【权限等级：标准模式】允许在当前项目目录内读取文件并执行常规分析与必要编辑；"
        "严禁访问或修改项目目录之外的文件，执行删除、格式化、覆写核心配置等高风险操作前必须先说明方案并征求用户确认。"
    ),
    "full": (
        "【权限等级：完全模式】允许在当前项目目录内自主读写文件、运行脚本、构建与测试，直接完成用户交代的任务并汇报结果。"
    ),
}

CHAT_MODE_RULE = (
    "【当前模式：日常聊天 (chat)】请以自然、亲切的纯对话方式直接与用户交流。"
    "不要扫描本地项目目录、不要执行终端命令、不要修改本地文件；"
    "仅针对用户的聊天内容（以及本次主动拖入的附件）作答。"
)


def _cleanup_old_attachments(att_root: Path, max_age_sec: float = 3600.0) -> None:
    """清理过期的临时附件子目录，防止 Kimi 误读历史遗留文件."""
    base = att_root / "attachments"
    if not base.is_dir():
        return
    now = time.time()
    for item in base.iterdir():
        try:
            if now - item.stat().st_mtime > max_age_sec:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
        except Exception:
            pass


def _prepare_cli_prompt(
    att_root: Path,
    user_text: str,
    attachments: list[dict[str, Any]],
    system_prompt: str = "",
    mode: str = "work",
    permission_level: str = "standard",
    reasoning_effort: str = "medium",
    thinking: bool = False,
    is_first_turn: bool = True,
) -> tuple[str, bool, Path]:
    """
    为每次请求创建独立的临时附件子目录 attachments/req_<id>/，彻底杜绝：
    1) Windows 32KB 命令行长度限制 (WinError 206)
    2) 空白文档被静默忽略导致模型胡编或串读历史旧文件！
    返回 (short_prompt, has_workspace_files, req_dir)。
    """
    _cleanup_old_attachments(att_root)
    req_dir = att_root / "attachments" / f"req_{uuid.uuid4().hex[:10]}"
    req_dir.mkdir(parents=True, exist_ok=True)

    parts: list[str] = []
    has_files = False

    if str(mode).lower() == "chat":
        parts.append(CHAT_MODE_RULE)
    else:
        perm_rule = PERMISSION_RULES.get(permission_level, PERMISSION_RULES["standard"])
        parts.append(perm_rule)

    if thinking:
        effort_hint = {
            "low": "请先简要思考再给出清晰结论。",
            "medium": "请进行充分的深度分析与推演后给出严谨回答。",
            "high": "请进行极深度的全面推理、多角度校验边界条件后再给出最终回答。",
        }.get(reasoning_effort, "")
        if effort_hint:
            parts.append(effort_hint)

    if is_first_turn and system_prompt.strip():
        parts.append(f"【回复风格要求】{system_prompt.strip()[:400]}")

    file_refs: list[str] = []
    empty_file_notices: list[str] = []
    for idx, att in enumerate(attachments, start=1):
        name = str(att.get("name") or f"file_{idx}")
        if att.get("kind") == "document":
            txt = load_attachment_text(att)
            if txt.strip():
                has_files = True
                safe_name = f"doc_{idx}_{att.get('id', idx)}.txt"
                dest = req_dir / safe_name
                dest.write_text(f"原文件名：{name}\n字数：{len(txt)}\n\n{txt}", encoding="utf-8")
                file_refs.append(f"- {dest}（原文件名：{name}，约 {len(txt)} 字）")
            else:
                # 明确告知模型这是一个空白/无文字内容的文件，绝对禁止猜测或沿用历史文档！
                empty_file_notices.append(
                    f"- {name}（原始字节大小：{att.get('size', 0)} 字节；经解析提取出的正文为 0 字，该文档内容为空白或不包含可提取文字）"
                )
        elif att.get("kind") == "image" and att.get("local_path"):
            has_files = True
            file_refs.append(f"- 图片路径：{att['local_path']}（文件名：{name}）")

    if file_refs:
        parts.append(
            "【本次新提交的文件】请只读取以下本次指定的本地文件再回答，不要去读其他历史文件：\n"
            + "\n".join(file_refs)
        )
    if empty_file_notices:
        parts.append(
            "【重要事实 · 空白文档】以下本次提交的文件没有任何文字内容：\n"
            + "\n".join(empty_file_notices)
            + "\n请务必如实告诉用户该文件是空白文档（没有任何文字内容），严禁编造内容，也严禁把以前聊过的其他文档内容套进来！"
        )

    clean_user = user_text.strip()
    if len(clean_user) > 3000:
        has_files = True
        pfile = req_dir / "user_message.txt"
        pfile.write_text(clean_user, encoding="utf-8")
        parts.append(f"用户的完整提问较长，已保存至 {pfile}，请先读取并完整回答。")
    elif clean_user:
        parts.append(clean_user)

    final_prompt = "\n\n".join(parts)
    if len(final_prompt) > 6000:
        pfile = req_dir / "full_prompt.txt"
        pfile.write_text(final_prompt, encoding="utf-8")
        return f"请读取文件 {pfile} 并严格按其中的权限要求与问题完整回答用户。", True, req_dir
    return final_prompt, has_files, req_dir


def _format_tool_call_label(tool_name: str, raw_args: Any) -> tuple[str, str]:
    """把 Kimi Code CLI 工具调用转成直观的中文阶段步骤描述与桌宠状态."""
    args: dict[str, Any] = {}
    if isinstance(raw_args, dict):
        args = raw_args
    elif isinstance(raw_args, str) and raw_args.strip():
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                args = parsed
        except Exception:
            pass

    lname = tool_name.lower()
    pet_state = "searching" if ("search" in lname or "web" in lname or "fetch" in lname) else "reading"

    def _short(val: Any, limit: int = 58) -> str:
        s = str(val or "").strip().replace("\r", " ").replace("\n", " ")
        return s[:limit] + ("..." if len(s) > limit else "")

    def _fname(val: Any) -> str:
        s = str(val or "").strip()
        if not s:
            return ""
        p = Path(s)
        return p.name or s

    if lname in ("bash", "shell", "runcommand", "run_command", "execute"):
        cmd = _short(args.get("command") or args.get("cmd") or "", 56)
        return (f"执行命令：{cmd}" if cmd else "执行终端命令"), "thinking"
    if "read" in lname or lname in ("view", "viewfile", "cat"):
        target = _fname(args.get("path") or args.get("file_path") or args.get("file") or "")
        return (f"读取文件：{target}" if target else "读取本地文件"), "reading"
    if "write" in lname or "create" in lname:
        target = _fname(args.get("path") or args.get("file_path") or args.get("file") or "")
        return (f"写入文件：{target}" if target else "写入文件"), "thinking"
    if "edit" in lname or "replace" in lname or "patch" in lname:
        target = _fname(args.get("path") or args.get("file_path") or args.get("file") or "")
        return (f"编辑文件：{target}" if target else "修改文件内容"), "thinking"
    if "glob" in lname or "list" in lname or "find" in lname:
        pat = _short(args.get("pattern") or args.get("path") or args.get("dir") or "", 42)
        return (f"查找文件：{pat}" if pat else "扫描目录文件"), "searching"
    if "grep" in lname or ("search" in lname and "web" not in lname):
        q = _short(args.get("pattern") or args.get("query") or "", 42)
        return (f"检索代码：{q}" if q else "检索代码内容"), "searching"
    if "web" in lname or "fetch" in lname or "url" in lname:
        q = _short(args.get("query") or args.get("url") or "", 48)
        return (f"联网查询：{q}" if q else "联网查询资料"), "searching"
    if "task" in lname or "agent" in lname:
        desc = _short(args.get("description") or args.get("prompt") or "", 48)
        return (f"执行子任务：{desc}" if desc else "执行子任务"), "thinking"

    first_val = next((_short(v, 42) for v in args.values() if v), "")
    label = f"调用 {tool_name}" + (f"：{first_val}" if first_val else "")
    return label, pet_state


def _extract_event_from_json(obj: Any) -> list[dict[str, Any]]:
    """兼容解析 Kimi Code CLI stream-json / NDJSON 的全部结构化事件（含详细阶段工具步骤与结果）."""
    events: list[dict[str, Any]] = []
    if not isinstance(obj, dict):
        return events

    # 捕获 session_id 用于后续多轮续聊
    sid = obj.get("session_id") or obj.get("sessionId")
    if isinstance(sid, str) and sid:
        events.append({"type": "cli_session", "session_id": sid})

    ev_type = str(obj.get("type") or obj.get("event") or "").lower()
    role = str(obj.get("role") or "").lower()

    # meta / system / user 事件仅提取 session_id，不把内部提示文本当成助手正文
    if role in ("meta", "system", "user"):
        return events

    # tool 执行结果：按 tool_call_id 标记对应步骤完成，并给出简洁一行摘要
    if role == "tool":
        tc_id = str(obj.get("tool_call_id") or obj.get("id") or "")
        raw_content = obj.get("content")
        text_out = ""
        if isinstance(raw_content, str):
            text_out = raw_content.strip()
        elif isinstance(raw_content, list):
            parts = [str(b.get("text") or "") for b in raw_content if isinstance(b, dict)]
            text_out = "\n".join(p for p in parts if p).strip()
        is_err = bool(obj.get("is_error")) or text_out.lower().startswith(("error:", "traceback", "failed"))
        lines = [ln.strip() for ln in text_out.splitlines() if ln.strip()]
        if is_err:
            summary = (lines[0][:56] + ("..." if len(lines[0]) > 56 else "")) if lines else "执行异常"
        elif lines:
            first_ln = lines[0][:44] + ("..." if len(lines[0]) > 44 else "")
            summary = f"已完成（{len(lines)} 行）· {first_ln}" if len(lines) > 1 else f"已完成 · {first_ln}"
        else:
            summary = "已完成"
        events.append({"type": "step_done", "id": tc_id, "ok": not is_err, "summary": summary})
        events.append({"type": "status", "state": "thinking", "label": "阶段完成，正在继续处理..."})
        return events

    # 1. 错误事件
    if ev_type == "error" or obj.get("error"):
        err = obj.get("error")
        msg = err.get("message") if isinstance(err, dict) else (obj.get("message") or str(err))
        events.append({"type": "error", "message": str(msg)})
        return events

    # 2. 思考过程增量
    for key in ("reasoning_content", "reasoning", "thinking"):
        val = obj.get(key)
        if isinstance(val, str) and val:
            events.append({"type": "reasoning", "delta": val})

    # 3. 工具调用（Kimi Code CLI v2.7+ 标准格式：role="assistant", tool_calls=[{id, function:{name, arguments}}]）
    tool_calls = obj.get("tool_calls")
    has_tool_calls = isinstance(tool_calls, list) and len(tool_calls) > 0
    if has_tool_calls:
        # 如果这一轮在调用工具的同时也说了阶段性说明（obj["content"]），作为阶段播报显示给用户
        inter_content = obj.get("content")
        if isinstance(inter_content, str) and inter_content.strip():
            events.append({"type": "step_note", "text": inter_content.strip()})
        elif isinstance(inter_content, list):
            for block in inter_content:
                if not isinstance(block, dict):
                    continue
                btype = str(block.get("type") or "").lower()
                if btype in ("think", "thinking", "reasoning"):
                    tv = block.get("think") or block.get("thinking") or block.get("text") or ""
                    if tv:
                        events.append({"type": "reasoning", "delta": str(tv)})
                elif btype == "text" and block.get("text"):
                    events.append({"type": "step_note", "text": str(block["text"]).strip()})

        for idx, tc in enumerate(tool_calls):
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            tname = str(fn.get("name") or tc.get("name") or "工具")
            targs = fn.get("arguments") if "arguments" in fn else tc.get("arguments")
            tc_id = str(tc.get("id") or f"tc_{int(time.time() * 1000)}_{idx}")
            title, pet_st = _format_tool_call_label(tname, targs)
            events.append({"type": "step_start", "id": tc_id, "tool": tname, "title": title})
            events.append({"type": "status", "state": pet_st, "label": title})
        return events

    if "tool" in ev_type or obj.get("tool_name"):
        tool_name = str(obj.get("tool_name") or obj.get("name") or "工具")
        title, st = _format_tool_call_label(tool_name, obj.get("arguments") or obj.get("input"))
        events.append({"type": "step_start", "id": str(obj.get("id") or uuid.uuid4().hex[:8]), "tool": tool_name, "title": title})
        events.append({"type": "status", "state": st, "label": title})

    # 4. 正文增量 / 完整消息文本
    delta = obj.get("delta")
    if isinstance(delta, dict):
        if isinstance(delta.get("reasoning_content"), str) and delta["reasoning_content"]:
            events.append({"type": "reasoning", "delta": delta["reasoning_content"]})
        if isinstance(delta.get("text"), str) and delta["text"]:
            events.append({"type": "content", "delta": delta["text"]})
        if isinstance(delta.get("content"), str) and delta["content"]:
            events.append({"type": "content", "delta": delta["content"]})
    elif isinstance(delta, str) and delta:
        events.append({"type": "content", "delta": delta})

    # 兼容 OpenAI-style choices 或 message.content 数组
    choices = obj.get("choices")
    if isinstance(choices, list) and choices:
        c0 = choices[0] if isinstance(choices[0], dict) else {}
        d0 = c0.get("delta") or c0.get("message") or {}
        if isinstance(d0, dict):
            if d0.get("reasoning_content"):
                events.append({"type": "reasoning", "delta": str(d0["reasoning_content"])})
            if d0.get("content"):
                events.append({"type": "content", "delta": str(d0["content"])})

    msg = obj.get("message")
    if isinstance(msg, dict) and msg.get("role") == "assistant":
        content = msg.get("content")
        if isinstance(content, str) and content:
            events.append({"type": "content", "delta": content})
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = str(block.get("type") or "").lower()
                if btype in ("think", "thinking", "reasoning"):
                    tv = block.get("think") or block.get("thinking") or block.get("text") or ""
                    if tv:
                        events.append({"type": "reasoning", "delta": str(tv)})
                elif btype == "text" and block.get("text"):
                    events.append({"type": "content", "delta": str(block["text"])})

    # 顶层 assistant content 数组（如 [{"type":"think",...},{"type":"text",...}]）
    if role == "assistant" and isinstance(obj.get("content"), list):
        for block in obj["content"]:
            if not isinstance(block, dict):
                continue
            btype = str(block.get("type") or "").lower()
            if btype in ("think", "thinking", "reasoning"):
                tv = block.get("think") or block.get("thinking") or block.get("text") or ""
                if tv:
                    events.append({"type": "reasoning", "delta": str(tv)})
            elif btype == "text" and block.get("text"):
                events.append({"type": "content", "delta": str(block["text"])})

    # 顶层直接 text / content（排除非 assistant 角色事件）
    if not events and role != "user":
        for key in ("text", "content", "result"):
            val = obj.get(key)
            if isinstance(val, str) and val and ev_type not in ("system", "init", "meta"):
                events.append({"type": "content", "delta": val})
                break

    return events


def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """在 Windows 下彻底终止 kimi.exe 及其派生的 bash/node/python 子进程树."""
    try:
        if proc.returncode is not None:
            return
        if os.name == "nt" and proc.pid:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            proc.terminate()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


async def stream_kimi_cli_chat(
    prompt_text: str,
    attachments: list[dict[str, Any]],
    model: str = "",
    system_prompt: str = "",
    cli_session_id: str = "",
    custom_path: str = "",
    project_dir: str = "",
    permission_level: str = "standard",
    mode: str = "work",
    thinking: bool = False,
    reasoning_effort: str = "medium",
    timeout_sec: int = 180,
) -> AsyncIterator[dict[str, Any]]:
    """无黑框调用本机 Kimi Code CLI，区分聊天 (chat) 与工作 (work) 模式，流式回传思考、工具状态与正文."""
    exe = find_kimi_executable(custom_path)
    if not exe:
        yield {
            "type": "error",
            "message": (
                "未检测到本机 Kimi Code CLI 引擎。请右键桌宠打开「设置 → Kimi 连接」，"
                "点击「一键安装 Kimi 引擎」并完成登录。"
            ),
        }
        return

    clean_mode = "chat" if str(mode).lower() == "chat" else "work"
    if clean_mode == "chat":
        default_ws = get_data_dir() / "kimi_chat_workspace"
        default_ws.mkdir(parents=True, exist_ok=True)
        workdir_path = default_ws
    else:
        default_ws = get_data_dir() / "kimi_workspace"
        default_ws.mkdir(parents=True, exist_ok=True)
        if project_dir and Path(project_dir).is_dir():
            workdir_path = Path(project_dir)
        else:
            workdir_path = default_ws
    workdir = str(workdir_path)

    full_prompt, has_workspace_files, req_dir = _prepare_cli_prompt(
        att_root=default_ws,
        user_text=prompt_text,
        attachments=attachments,
        system_prompt=system_prompt,
        mode=clean_mode,
        permission_level=permission_level,
        reasoning_effort=reasoning_effort,
        thinking=thinking,
        is_first_turn=not bool(cli_session_id),
    )

    args = [exe, "--prompt", full_prompt, "--output-format", "stream-json"]
    if has_workspace_files and workdir_path.resolve() != default_ws.resolve():
        args.extend(["--add-dir", str(req_dir)])
    if model and model not in ("auto", "default", "kimi-default"):
        args.extend(["--model", model])
    if cli_session_id:
        args.extend(["--session", cli_session_id])

    yield {
        "type": "status",
        "state": "reading" if has_workspace_files else "thinking",
        "label": (
            "Kimi 正在阅读文件内容..."
            if has_workspace_files
            else ("Kimi 正在聊天回复..." if clean_mode == "chat" else "Kimi 工作引擎正在思考...")
        ),
    }

    env = dict(os.environ)
    bash_path = _find_git_bash()
    if os.name == "nt" and not bash_path and not env.get("KIMI_SHELL_PATH"):
        yield {
            "type": "error",
            "message": (
                "当前电脑尚未安装 Git Bash（Kimi 本机引擎需要它才能运行）。\n"
                "请右键桌宠 →「设置 → Kimi 连接」点击「安装 Git 运行环境」，安装完成后即可使用；"
                "或者直接在下方「方式二」填入 Kimi 官方 API Key（无需安装 Git）。"
            ),
        }
        return
    if bash_path and not env.get("KIMI_SHELL_PATH"):
        env["KIMI_SHELL_PATH"] = bash_path
    if bash_path:
        bash_dir = str(Path(bash_path).parent)
        cur_path = env.get("PATH", "")
        if bash_dir.lower() not in cur_path.lower():
            env["PATH"] = f"{bash_dir};{cur_path}" if cur_path else bash_dir

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
            env=env,
            limit=32 * 1024 * 1024,  # 32MB 行缓冲，避免大文件 tool JSON 行超出默认 64KB 导致流断开 (network error)
            creationflags=creationflags,
        )
    except Exception as exc:
        yield {"type": "error", "message": f"启动 Kimi 引擎失败：{exc}"}
        return

    assert proc.stdout is not None and proc.stderr is not None
    got_content = False
    saw_json = False
    stderr_lines: list[str] = []
    max_wait = max(30, min(600, int(timeout_sec or 180)))

    async def _drain_stderr() -> None:
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            stderr_lines.append(line.decode("utf-8", errors="replace").strip())

    stderr_task = asyncio.create_task(_drain_stderr())

    try:
        while True:
            try:
                raw_line = await asyncio.wait_for(proc.stdout.readline(), timeout=max_wait)
            except asyncio.TimeoutError:
                _kill_process_tree(proc)
                yield {"type": "error", "message": f"Kimi 响应超过 {max_wait} 秒已自动超时中止（可在「设置 → 时间与轮询」调大超时时间）。"}
                return
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
                saw_json = True
                parsed = _extract_event_from_json(obj)
                for ev in parsed:
                    if ev["type"] == "content":
                        if not got_content:
                            got_content = True
                            yield {"type": "status", "state": "speaking", "label": "Kimi 正在整理回复..."}
                    yield ev
            except json.JSONDecodeError:
                # 若已经收到标准 stream-json 事件，子命令泄出的裸文本不再拼进最终正文，避免杂讯污染回复
                if not saw_json:
                    if not got_content:
                        got_content = True
                        yield {"type": "status", "state": "speaking", "label": "Kimi 正在回复..."}
                    yield {"type": "content", "delta": line + "\n"}

        rc = await proc.wait()
        await stderr_task
        if rc != 0 and not got_content:
            err_detail = "\n".join(x for x in stderr_lines if x)[-400:]
            if "login" in err_detail.lower() or "auth" in err_detail.lower() or "token" in err_detail.lower():
                yield {
                    "type": "error",
                    "message": "Kimi 本机引擎尚未登录账号。请右键桌宠 →「设置」→「Kimi 连接」点击「登录 Kimi 账号」。",
                }
            else:
                yield {
                    "type": "error",
                    "message": f"Kimi 引擎退出异常 (code={rc})：{err_detail or '请检查 Kimi Code CLI 是否已登录或更新至最新版。'}",
                }
            return
        yield {"type": "done", "usage": {}}
    except asyncio.CancelledError:
        _kill_process_tree(proc)
        stderr_task.cancel()
        raise
    finally:
        if proc.returncode is None:
            _kill_process_tree(proc)
