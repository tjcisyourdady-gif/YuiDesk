"""Qt 主线程与 FastAPI 后台线程之间的安全事件桥接."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class DesktopBridge(QObject):
    # 桌宠状态切换: state, bubble_text
    pet_state_changed = Signal(str, str)
    # 定时桌宠动画（用于独立养成动作）: state, bubble_text, duration_sec
    pet_timed_state_requested = Signal(str, str, float)
    # 独立养成浮窗控制: "toggle" | "show" | "hide"
    care_window_requested = Signal(str)
    # 桌宠配置/皮肤变更
    pet_settings_changed = Signal(dict)
    # 切换聊天窗模式: mode ("dialog" | "hide" | "toggle" | "settings")
    window_mode_requested = Signal(str)
    # 动态调整桌宠下方悬浮对话框尺寸（宽, 高）
    dialog_height_requested = Signal(int)
    dialog_size_requested = Signal(int, int)
    # 触发区域截屏
    screenshot_requested = Signal()
    # 打开原生项目文件夹选择器
    pick_project_requested = Signal()
    # 向聊天前端注入新上传的附件或快捷指令 (payload JSON dict)
    frontend_event = Signal(str, dict)
    # 应用退出
    quit_requested = Signal()
