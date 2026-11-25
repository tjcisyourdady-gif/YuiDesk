"""YuiDesk 应用主入口：启动本地 FastAPI 服务 + PySide6 桌宠、桌宠下方对话框、截屏与快捷键."""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn
from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QFileDialog

from app.database import Database
from app.desktop.bridge import DesktopBridge
from app.desktop.care_window import CareWindow
from app.desktop.chat_window import ChatWindow
from app.desktop.hotkeys import WinHotkeyManager
from app.desktop.pet_window import PetWindow
from app.desktop.screenshot import ScreenshotOverlay
from app.desktop.tray import TrayManager, create_app_icon
from app.doc_parser import process_uploaded_file, process_uploaded_image
from app.kimi_cli_bridge import find_kimi_executable
from app.pet_care import PetCareEngine


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _set_windows_startup(enabled: bool) -> None:
    if os.name != "nt":
        return
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}"'
                else:
                    cmd = f'"{sys.executable}" "{Path(__file__).resolve()}"'
                winreg.SetValueEx(key, "YuiDesk", 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, "YuiDesk")
                except FileNotFoundError:
                    pass
    except Exception:
        pass


class _QuietUvicornServer(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        return


class _BackendThread(threading.Thread):
    def __init__(self, app, port: int) -> None:
        super().__init__(daemon=True)
        self._config = uvicorn.Config(
            app=app,
            host="127.0.0.1",
            port=port,
            log_config=None,
            access_log=False,
        )
        self._server = _QuietUvicornServer(self._config)

    def run(self) -> None:
        self._server.run()

    def stop(self) -> None:
        self._server.should_exit = True


def main() -> int:
    # 防止在 OneDrive/网络盘/非标准权限目录下 QtWebEngine 沙盒启动白屏崩溃
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

    # pythonw.exe 与 PyInstaller --windowed 模式下 stdout/stderr 为 None，重定向到日志文件避免第三方库崩溃
    from app.paths import get_data_dir

    if sys.stdout is None or sys.stderr is None:
        log_file = open(get_data_dir() / "yuidesk.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = log_file
        if sys.stderr is None:
            sys.stderr = log_file

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("YuiDesk")
    qt_app.setQuitOnLastWindowClosed(False)

    # 单实例守护：若已经运行着一个 YuiDesk，再次双击直接唤醒已有桌宠与对话框，不重复开双份
    instance_key = "YuiDesk_SingleInstance_v1"
    if not os.environ.get("YUIDESK_ALLOW_MULTI"):
        probe = QLocalSocket()
        probe.connectToServer(instance_key)
        if probe.waitForConnected(250):
            probe.write(b"wakeup")
            probe.flush()
            probe.waitForBytesWritten(250)
            probe.disconnectFromServer()
            return 0
        QLocalServer.removeServer(instance_key)

    app_icon = create_app_icon()
    qt_app.setWindowIcon(app_icon)

    db = Database()
    care = PetCareEngine()
    bridge = DesktopBridge()
    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    from app.server import create_app

    fastapi_app = create_app(db=db, bridge=bridge, care=care, port=port)
    backend = _BackendThread(fastapi_app, port)
    backend.start()

    deadline = time.perf_counter() + 5.0
    while time.perf_counter() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.15):
                break
        except OSError:
            time.sleep(0.05)

    settings = db.get_settings()
    pet = PetWindow(settings)
    chat = ChatWindow(base_url)
    chat.setWindowIcon(app_icon)
    care_win = CareWindow(base_url)
    care_win.setWindowIcon(app_icon)
    screenshot = ScreenshotOverlay()

    # 单实例唤醒服务
    single_server = QLocalServer(qt_app)
    if not os.environ.get("YUIDESK_ALLOW_MULTI"):
        def _on_second_instance() -> None:
            conn = single_server.nextPendingConnection()
            if conn:
                conn.readAll()
                conn.close()
            pet.show()
            pet.raise_()
            chat.show_under_pet(pet)

        single_server.newConnection.connect(_on_second_instance)
        single_server.listen(instance_key)

    # ---------- 信号连接 ----------

    bridge.pet_state_changed.connect(pet.set_state)
    bridge.pet_timed_state_requested.connect(pet.set_timed_state)

    def _on_care_window(action: str) -> None:
        if action == "hide":
            care_win.hide()
        elif action == "show":
            care_win.show_near_pet(pet)
        else:
            care_win.toggle_near_pet(pet)

    bridge.care_window_requested.connect(_on_care_window)

    def _on_settings_changed(new_settings: dict[str, Any]) -> None:
        pet.apply_settings(new_settings)
        care_win.refresh()
        _set_windows_startup(bool(new_settings.get("launch_at_startup", False)))
        _register_hotkeys(new_settings)
        poll_sec = max(15, min(600, int(new_settings.get("care_poll_interval_sec", 60) or 60)))
        care_sync_timer.setInterval(poll_sec * 1000)

    bridge.pet_settings_changed.connect(_on_settings_changed)

    def _on_window_mode(action: str) -> None:
        if action in ("bubble", "dialog", "workspace"):
            chat.show_under_pet(pet)
        elif action == "settings":
            chat.show_settings()
        elif action == "hide":
            chat.hide()
        elif action == "toggle":
            chat.toggle_under_pet(pet)

    bridge.window_mode_requested.connect(_on_window_mode)
    bridge.dialog_height_requested.connect(chat.set_dialog_height)
    bridge.dialog_size_requested.connect(chat.set_dialog_size)
    bridge.screenshot_requested.connect(lambda: QTimer.singleShot(120, screenshot.start_capture))
    bridge.frontend_event.connect(chat.dispatch_event)

    def _on_pick_project() -> None:
        cur = db.get_settings()
        start_dir = cur.get("active_project_dir") or str(Path.home() / "Desktop")
        chosen = QFileDialog.getExistingDirectory(chat, "选择项目文件夹", start_dir)
        if not chosen:
            chat.dispatch_event("sync_settings", {"settings": cur})
            return
        recent = [p for p in (cur.get("recent_projects") or []) if p != chosen and Path(p).is_dir()]
        recent.insert(0, chosen)
        updated = db.update_settings({"active_project_dir": chosen, "recent_projects": recent[:10]})
        chat.dispatch_event("project_selected", {"settings": updated})
        chat.show_under_pet(pet)

    bridge.pick_project_requested.connect(_on_pick_project)

    pet.clicked_chat.connect(lambda: chat.toggle_under_pet(pet))
    pet.care_triggered.connect(lambda: care_win.toggle_near_pet(pet))
    pet.moved.connect(lambda: (chat.sync_to_pet(pet), care_win.sync_to_pet(pet)))

    def _on_head_patted() -> None:
        res = care.perform_action("pet")
        pet.set_timed_state(str(res.get("pet_state") or "pet_head"), str(res.get("bubble") or "被摸头好舒服"), 3.2)
        pet.set_hungry_flag(bool(res.get("state", {}).get("is_hungry")))
        care_win.refresh()

    pet.head_patted.connect(_on_head_patted)

    def _on_files_eaten(count: int) -> None:
        st = care.reward_file_eaten(count)
        pet.set_hungry_flag(bool(st.get("is_hungry")))
        care_win.refresh()

    pet.files_eaten_completed.connect(_on_files_eaten)

    # 按设置间隔本地静默轮询同步养成饱食状态（完全不联网、不调用 AI）
    care_sync_timer = QTimer(pet)
    care_sync_timer.timeout.connect(lambda: pet.set_hungry_flag(bool(care.get_state().get("is_hungry"))))
    init_poll_sec = max(15, min(600, int(settings.get("care_poll_interval_sec", 60) or 60)))
    care_sync_timer.start(init_poll_sec * 1000)
    pet.set_hungry_flag(bool(care.get_state().get("is_hungry")))

    # 本地定时轮询提醒（支持按间隔分钟轮询 + 每日定点 HH:MM 提醒）
    reminder_state = {"last_interval_ts": time.time(), "last_daily_key": ""}

    def _on_reminder_tick() -> None:
        cur = db.get_settings()
        if not cur.get("reminder_enabled", False):
            reminder_state["last_interval_ts"] = time.time()
            return
        msg = str(cur.get("reminder_text") or "").strip() or "已经专注一段时间啦，起来活动一下、喝口水吧"
        now_ts = time.time()
        interval_min = max(0, min(240, int(cur.get("reminder_interval_min", 45) or 0)))
        daily_hm = str(cur.get("reminder_daily_time") or "").strip()

        triggered = False
        if daily_hm:
            now_dt = time.localtime(now_ts)
            cur_hm = f"{now_dt.tm_hour:02d}:{now_dt.tm_min:02d}"
            today_key = f"{now_dt.tm_year}-{now_dt.tm_mon:02d}-{now_dt.tm_mday:02d} {cur_hm}"
            if cur_hm == daily_hm and reminder_state["last_daily_key"] != today_key:
                reminder_state["last_daily_key"] = today_key
                triggered = True
        if not triggered and interval_min > 0 and (now_ts - reminder_state["last_interval_ts"]) >= interval_min * 60:
            reminder_state["last_interval_ts"] = now_ts
            triggered = True

        if triggered:
            bubble_dur = float(max(4, min(15, int(cur.get("pet_bubble_duration_sec", 4) or 4) + 2)))
            pet.set_timed_state("stretch", msg, duration=bubble_dur)

    reminder_timer = QTimer(pet)
    reminder_timer.timeout.connect(_on_reminder_tick)
    reminder_timer.start(15000)

    pet.new_chat_triggered.connect(
        lambda: (chat.show_under_pet(pet), chat.dispatch_event("new_chat", {}))
    )

    def _on_web_search_toggled(enabled: bool) -> None:
        updated = db.update_settings({"web_search_enabled": enabled})
        pet.apply_settings(updated)
        chat.dispatch_event("sync_settings", {"settings": updated})
        pet.show_bubble("联网搜索已开启" if enabled else "联网搜索已关闭", duration=2.2)

    pet.web_search_toggled.connect(_on_web_search_toggled)

    def _on_auto_walk_toggled(enabled: bool) -> None:
        updated = db.update_settings({"pet_auto_walk": enabled})
        pet.apply_settings(updated)
        chat.dispatch_event("sync_settings", {"settings": updated})
        pet.show_bubble("已开启桌面漫游" if enabled else "已关闭桌面漫游", duration=2.2)

    pet.auto_walk_toggled.connect(_on_auto_walk_toggled)

    def _on_skin_selected(skin_id: str) -> None:
        from app.skins import get_skin

        updated = db.update_settings({"active_skin_id": skin_id})
        pet.apply_settings(updated)
        chat.dispatch_event("sync_settings", {"settings": updated})
        care_win.refresh()
        sk = get_skin(skin_id)
        pet.set_state("happy", f"已切换为 {sk.get('name', skin_id).split('（')[0]}")

    pet.skin_selected.connect(_on_skin_selected)
    pet.upload_triggered.connect(
        lambda: (chat.show_under_pet(pet), QTimer.singleShot(180, lambda: chat.dispatch_event("trigger_upload", {})))
    )
    pet.settings_triggered.connect(lambda: chat.show_settings())
    pet.screenshot_triggered.connect(lambda: QTimer.singleShot(120, screenshot.start_capture))

    def _handle_read_files(paths: list[str]) -> None:
        current_settings = db.get_settings()
        provider = db.get_provider(current_settings["active_provider_id"], include_raw_key=True)
        if provider and provider.get("id") == "kimi_cli":
            has_llm = bool(find_kimi_executable(str(current_settings.get("kimi_cli_path") or "")))
        else:
            has_llm = bool(provider and (provider.get("api_key") or provider.get("id") == "ollama"))

        def _worker() -> None:
            t0 = time.perf_counter()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            parsed_attachments: list[dict[str, Any]] = []
            try:
                for p in paths:
                    path_obj = Path(p)
                    if not path_obj.is_file():
                        continue
                    raw = path_obj.read_bytes()
                    att = loop.run_until_complete(
                        process_uploaded_file(path_obj.name, raw, provider=provider)
                    )
                    att_slim = {k: v for k, v in att.items() if k != "data_url"}
                    parsed_attachments.append(att_slim)

                # 保证放大镜研究动画至少播放 1.5 秒，体验更连贯生动
                remain = 1.5 - (time.perf_counter() - t0)
                if remain > 0:
                    time.sleep(remain)

                if not parsed_attachments:
                    bridge.pet_state_changed.emit("idle", "")
                    return

                bridge.window_mode_requested.emit("dialog")
                if has_llm:
                    bridge.pet_state_changed.emit("thinking", "研究完啦，正在告诉你是什么")
                    prompt = (
                        f"帮我看看这 {len(parsed_attachments)} 个文件分别是什么，并用简洁清晰的要点概括各自的主要内容。"
                        if len(parsed_attachments) > 1
                        else "帮我看看这个文件是什么，并用简洁清晰的要点概括主要内容。"
                    )
                    bridge.frontend_event.emit(
                        "inspect_and_explain",
                        {"attachments": parsed_attachments, "prompt": prompt},
                    )
                else:
                    # 即使还没配置 API Key，也在对话框里直接展示每个文件的本地解析结果
                    lines = [f"共读取了 {len(parsed_attachments)} 个文件：\n"]
                    for idx, att in enumerate(parsed_attachments, start=1):
                        if att.get("kind") == "image":
                            lines.append(
                                f"{idx}. **{att['name']}**（图片 · {att.get('width', '?')}×{att.get('height', '?')}）"
                            )
                        else:
                            preview = (att.get("preview") or "").strip().replace("\n", " ")[:120]
                            lines.append(
                                f"{idx}. **{att['name']}**（文档 · 约 {att.get('chars', 0)} 字）\n"
                                + (f"   > 摘要预览：{preview}..." if preview else "")
                            )
                    lines.append("\n> 提示：右键桌宠打开「设置」填入 Kimi 或其他模型 API Key 后，可自动给出深度 AI 总结。")
                    bridge.pet_state_changed.emit("happy", "研究完啦，已为你列出内容")
                    bridge.frontend_event.emit(
                        "local_file_report",
                        {"attachments": parsed_attachments, "report": "\n".join(lines)},
                    )
            except Exception as exc:
                bridge.pet_state_changed.emit("error", f"读取失败：{exc}")
            finally:
                loop.close()

        threading.Thread(target=_worker, daemon=True).start()

    pet.files_read_requested.connect(_handle_read_files)

    def _handle_clipboard_action(action: str) -> None:
        clip_text = (QApplication.clipboard().text() or "").strip()
        if not clip_text:
            pet.show_bubble("剪贴板为空", duration=3.0)
            return
        prompts = {
            "translate": f"请帮我地道流畅地翻译以下内容（中文译英文，外文译中文）：\n\n{clip_text}",
            "summarize": f"请帮我提炼以下内容的核心要点：\n\n{clip_text}",
            "explain": f"请帮我解释以下代码的功能和关键逻辑：\n\n```\n{clip_text}\n```",
        }
        chat.show_under_pet(pet)
        chat.dispatch_event("quick_send", {"content": prompts.get(action, clip_text)})

    pet.clipboard_action.connect(_handle_clipboard_action)

    def _on_screenshot_captured(png_bytes: bytes) -> None:
        att = process_uploaded_image(f"screenshot_{int(time.time())}.png", png_bytes)
        att_slim = {k: v for k, v in att.items() if k != "data_url"}
        chat.show_under_pet(pet)
        chat.dispatch_event("add_attachment", {"attachment": att_slim, "focus_input": True})
        pet.set_state("happy", "截屏已添加到对话框")

    screenshot.captured.connect(_on_screenshot_captured)

    # ---------- 全局快捷键 ----------
    hotkeys = WinHotkeyManager()
    qt_app.installNativeEventFilter(hotkeys)

    def _register_hotkeys(cur_settings: dict[str, Any]) -> None:
        hotkeys.unregister_all()
        hotkeys.register(cur_settings.get("hotkey_toggle", "Alt+Space"), lambda: chat.toggle_under_pet(pet))
        hotkeys.register(cur_settings.get("hotkey_screenshot", "Alt+S"), lambda: screenshot.start_capture())

    _register_hotkeys(settings)

    # ---------- 系统托盘 ----------
    def _quit_app() -> None:
        hotkeys.unregister_all()
        tray.hide()
        backend.stop()
        qt_app.quit()

    tray = TrayManager(
        parent=qt_app,
        on_toggle_chat=lambda: chat.toggle_under_pet(pet),
        on_screenshot=lambda: QTimer.singleShot(120, screenshot.start_capture),
        on_toggle_pet=lambda: pet.hide() if pet.isVisible() else pet.show(),
        on_open_settings=lambda: chat.show_settings(),
        on_quit=_quit_app,
    )
    pet.quit_triggered.connect(_quit_app)
    bridge.quit_requested.connect(_quit_app)

    # 启动时默认只显示桌宠，不打开任何配置或对话窗口
    pet.show()
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
