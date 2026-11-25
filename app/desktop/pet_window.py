"""透明无边框置顶桌宠窗口（高清日漫动画 + 仰头张嘴接文件 + 吃掉/读取双选项 + 手持图标啃食与放大镜研究）."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import math
import os
import random
import time
from pathlib import Path
from typing import Any


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.wintypes.HWND),
        ("wFunc", ctypes.wintypes.UINT),
        ("pFrom", ctypes.wintypes.LPCWSTR),
        ("pTo", ctypes.wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", ctypes.wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.wintypes.LPCWSTR),
    ]


def _move_to_recycle_bin(file_path: str) -> bool:
    """安全移入 Windows 回收站（可随时还原，绝不永久删除）."""
    if os.name != "nt" or not file_path or not Path(file_path).exists():
        return False
    try:
        op = _SHFILEOPSTRUCTW()
        op.wFunc = 3  # FO_DELETE
        op.pFrom = file_path + "\0\0"
        op.fFlags = 0x0040 | 0x0010 | 0x0004  # FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
        res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return res == 0 and not op.fAnyOperationsAborted
    except Exception:
        return False

from PySide6.QtCore import QEvent, QFileInfo, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QFont,
    QLinearGradient,
    QMovie,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileIconProvider,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QWidget,
)

from app.desktop.pet_renderer import AnimePetRenderer
from app.skins import get_skin, list_skins


class PetWindow(QWidget):
    clicked_chat = Signal()
    care_triggered = Signal()
    head_patted = Signal()
    files_eaten_completed = Signal(int)
    new_chat_triggered = Signal()
    web_search_toggled = Signal(bool)
    auto_walk_toggled = Signal(bool)
    skin_selected = Signal(str)
    upload_triggered = Signal()
    screenshot_triggered = Signal()
    files_read_requested = Signal(list)  # list[str]
    clipboard_action = Signal(str)
    settings_triggered = Signal()
    moved = Signal()
    quit_triggered = Signal()

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(None)
        self._settings = dict(settings)
        self._skin = get_skin(settings.get("active_skin_id", "default_sprite"))
        self._renderer = AnimePetRenderer()
        self._icon_provider = QFileIconProvider()

        self._state = "idle"
        self._idle_submode = "normal"  # normal | guitar | tea
        self._start_time = time.perf_counter()
        self._last_interaction = time.perf_counter()
        self._state_reset_at = 0.0

        self._bubble_text = ""
        self._bubble_until = 0.0

        self._dragging = False
        self._drag_moved = False
        self._drag_offset = QPoint()
        self._last_drag_x = 0
        self._drag_vx = 0.0

        # 多文件拖放状态
        self._pending_drop_paths: list[str] = []
        self._pending_drop_icons: list[tuple[str, QPixmap]] = []
        # 吃掉动画队列：[(full_path, filename, pixmap), ...]
        self._eat_queue: list[tuple[str, str, QPixmap]] = []
        self._eat_total = 0
        self._eat_index = 0
        self._eat_recycled = 0
        self._eat_item_start = 0.0
        self._eat_duration_per_item = 2.1  # 每个文件啃 3 口约 2.1 秒
        # 读取研究动画手持图标
        self._inspect_icons: list[tuple[str, QPixmap]] = []
        # 边缘扒边状态: None | "left" | "right"
        self._edge_side: str | None = None
        # 头顶轻抚摸头检测（纯本地养成互动）
        self._pat_last_x = 0.0
        self._pat_last_dir = 0
        self._pat_flips = 0
        self._pat_window_start = 0.0
        self._pat_cooldown_until = 0.0
        # 养成状态标志（饿肚子时待机自动切换 hungry 撒娇）
        self._is_hungry = False
        # 桌面自由散步状态
        self._walk_dir = 0  # -1 左走 | 1 右走 | 0 停止
        self._walk_until = 0.0
        self._walk_speed = 46.0
        self._walk_last_tick = time.perf_counter()
        self._walk_accum_x = 0.0

        self._movie: QMovie | None = None
        self._current_asset_path = ""
        self._pixmap_cache: dict[str, QPixmap] = {}

        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._apply_window_flags()

        self._hide_dock_timer = QTimer(self)
        self._hide_dock_timer.setSingleShot(True)
        self._hide_dock_timer.setInterval(420)
        self._hide_dock_timer.timeout.connect(self._hide_dock_if_outside)

        self._dock: QWidget | None = None
        self._drop_choice_dock: QWidget | None = None
        self._dock = self._build_action_dock()
        self._drop_choice_dock = self._build_drop_choice_dock()

        # 60 FPS 动画驱动
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._on_tick)
        self._anim_timer.start(16)

        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._on_idle_director)
        self._idle_timer.start(10000)

        self.apply_settings(settings)
        self._place_initial_position()

    def _apply_window_flags(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._settings.get("pet_always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()

    def _build_action_dock(self) -> QWidget:
        dock = QWidget(self)
        dock.setObjectName("actionDock")
        dock.setStyleSheet(
            """
            #actionDock {
                background-color: rgba(255, 253, 250, 246);
                border: 1px solid rgba(229, 107, 77, 130);
                border-radius: 15px;
            }
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 10px;
                padding: 4px 10px;
                font-family: "Microsoft YaHei UI";
                font-size: 12px;
                font-weight: 600;
                color: #2B2F36;
            }
            QPushButton:hover {
                background-color: #E56B4D;
                color: #FFFFFF;
            }
            """
        )
        layout = QHBoxLayout(dock)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(2)

        for label, cb in [
            ("对话", lambda: self.clicked_chat.emit()),
            ("养成", lambda: self.care_triggered.emit()),
            ("文件", lambda: self.upload_triggered.emit()),
        ]:
            btn = QPushButton(label, dock)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(cb)
            layout.addWidget(btn)

        dock.adjustSize()
        dock.installEventFilter(self)
        dock.hide()
        return dock

    def _build_drop_choice_dock(self) -> QWidget:
        """松开拖入文件后弹出的双选项卡片：吃掉 / 读取."""
        dock = QWidget(self)
        dock.setObjectName("dropChoiceDock")
        dock.setStyleSheet(
            """
            #dropChoiceDock {
                background-color: rgba(255, 253, 250, 252);
                border: 1.5px solid #E56B4D;
                border-radius: 16px;
            }
            QPushButton {
                background-color: #F6F2EC;
                border: 1px solid #E4DDD4;
                border-radius: 10px;
                padding: 5px 14px;
                font-family: "Microsoft YaHei UI";
                font-size: 12.5px;
                font-weight: 600;
                color: #22252A;
            }
            QPushButton:hover {
                background-color: #E56B4D;
                border-color: #E56B4D;
                color: #FFFFFF;
            }
            QPushButton#btnCancelDrop {
                background: transparent;
                border: none;
                padding: 4px 6px;
                color: #888E99;
                font-weight: 500;
            }
            QPushButton#btnCancelDrop:hover {
                background: transparent;
                color: #E56B4D;
            }
            """
        )
        layout = QHBoxLayout(dock)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(6)

        btn_eat = QPushButton("吃掉", dock)
        btn_eat.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_eat.clicked.connect(self._on_choose_eat)
        layout.addWidget(btn_eat)

        btn_read = QPushButton("读取", dock)
        btn_read.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_read.clicked.connect(self._on_choose_read)
        layout.addWidget(btn_read)

        btn_cancel = QPushButton("×", dock)
        btn_cancel.setObjectName("btnCancelDrop")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setToolTip("取消")
        btn_cancel.clicked.connect(self._cancel_drop_choice)
        layout.addWidget(btn_cancel)

        dock.adjustSize()
        dock.hide()
        return dock

    def eventFilter(self, obj, event):  # type: ignore[override]
        if self._dock is not None and obj is self._dock:
            if event.type() == QEvent.Type.Enter:
                self._hide_dock_timer.stop()
            elif event.type() == QEvent.Type.Leave:
                self._hide_dock_timer.start()
        return super().eventFilter(obj, event)

    def _layout_docks(self) -> None:
        pet_rect = self._pet_draw_rect()
        if self._dock is not None:
            self._dock.adjustSize()
            dx = int((self.width() - self._dock.width()) / 2.0)
            dy = int(max(44.0, pet_rect.top() - self._dock.height() + 8.0))
            self._dock.move(dx, dy)
            self._dock.raise_()
        if self._drop_choice_dock is not None:
            self._drop_choice_dock.adjustSize()
            dx = int((self.width() - self._drop_choice_dock.width()) / 2.0)
            dy = int(max(44.0, pet_rect.top() - self._drop_choice_dock.height() + 8.0))
            self._drop_choice_dock.move(dx, dy)
            self._drop_choice_dock.raise_()

    def _pet_box_size(self) -> int:
        scale_pct = max(70, min(160, int(self._settings.get("pet_scale", 100))))
        return int(176 * scale_pct / 100)

    def apply_settings(self, settings: dict[str, Any]) -> None:
        old_top = self._settings.get("pet_always_on_top", True)
        self._settings = dict(settings)
        self._skin = get_skin(settings.get("active_skin_id", "default_sprite"))
        self._pixmap_cache.clear()
        self._current_asset_path = ""
        self._reload_media_for_state(self._state)

        pet_sz = self._pet_box_size()
        self.setFixedSize(pet_sz + 56, pet_sz + 94)
        self._layout_docks()

        opacity = max(35, min(100, int(settings.get("pet_opacity", 100)))) / 100.0
        self.setWindowOpacity(opacity)

        # 动态同步轮询间隔与漫游开关
        idle_sec = max(5, min(120, int(settings.get("pet_idle_interval_sec", 10) or 10)))
        self._idle_timer.setInterval(idle_sec * 1000)
        if not settings.get("pet_auto_walk", True) and self._state in ("walk_left", "walk_right"):
            self._walk_dir = 0
            self._walk_until = 0.0
            self._state_reset_at = 0.0
            self._state = f"peek_{self._edge_side}" if self._edge_side else "idle"
            self._reload_media_for_state(self._state)

        if old_top != self._settings.get("pet_always_on_top", True):
            self._apply_window_flags()
        self.update()

    def _place_initial_position(self) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            return
        avail = screen.availableGeometry()
        x = avail.right() - self.width() - 60
        y = avail.top() + int(avail.height() * 0.22)
        self.move(x, y)

    def set_hungry_flag(self, is_hungry: bool) -> None:
        self._is_hungry = bool(is_hungry)

    def set_timed_state(self, state: str, bubble_text: str = "", duration: float = 3.8) -> None:
        """播放固定时长的养成专属动画，结束后自动恢复待机或扒边状态."""
        now = time.perf_counter()
        self._last_interaction = now
        self._state = state
        self._state_reset_at = now + max(1.5, duration)
        if state in ("walk_left", "walk_right"):
            self._edge_side = None
            self._walk_dir = -1 if state == "walk_left" else 1
            self._walk_until = self._state_reset_at
            self._walk_last_tick = now
            self._walk_accum_x = 0.0
        else:
            self._walk_dir = 0
        self._reload_media_for_state(state)
        if bubble_text:
            self.show_bubble(bubble_text, duration=min(4.8, duration))
        self.update()

    def set_state(self, state: str, bubble_text: str = "") -> None:
        now = time.perf_counter()
        self._last_interaction = now
        self._state = state
        if state in ("walk_left", "walk_right"):
            self._edge_side = None
            self._walk_dir = -1 if state == "walk_left" else 1
            self._walk_until = now + 4.0
            self._walk_last_tick = now
            self._walk_accum_x = 0.0
            self._state_reset_at = now + 4.0
        else:
            self._walk_dir = 0
            # 在 inspect_file / reading / thinking 阶段保留手中正在研究的文件图标，直到回复/完成/出错再放下
            if state not in ("inspect_file", "reading", "thinking"):
                self._inspect_icons = []
            if state == "happy":
                self._state_reset_at = now + 3.2
            elif state == "error":
                self._state_reset_at = now + 4.8
            elif state in ("sit_swing", "music_dance", "shy_blush", "proud_pose"):
                self._state_reset_at = now + 4.5
            else:
                self._state_reset_at = 0.0
        self._reload_media_for_state(state)

        if bubble_text:
            self.show_bubble(bubble_text, duration=4.0)
        elif state in ("happy", "error"):
            lines = (self._skin.get("bubbles") or {}).get(state) or []
            if lines:
                self.show_bubble(random.choice(lines), duration=3.5)
        self.update()

    def show_bubble(self, text: str, duration: float | None = None) -> None:
        self._bubble_text = text.strip()
        default_dur = float(max(2, min(15, int(self._settings.get("pet_bubble_duration_sec", 4) or 4))))
        eff_dur = default_dur if duration is None else float(duration)
        self._bubble_until = time.perf_counter() + eff_dur
        self.update()

    def _pick_asset_for_current_frame(self, state: str, t: float) -> str:
        assets = self._skin.get("assets") or {}
        if not assets:
            return ""
        if state == "eating":
            # 张大嘴咬下 <-> 鼓腮咀嚼 交替
            elapsed = time.perf_counter() - self._eat_item_start
            phase = int(elapsed / 0.34) % 2
            if phase == 0:
                return assets.get("eat_open") or assets.get("file_catch") or assets.get("idle", "")
            return assets.get("eat_chew") or assets.get("happy") or assets.get("idle", "")
        if state == "inspect_file" or (state == "reading" and self._inspect_icons):
            return assets.get("inspect_file") or assets.get("searching") or assets.get("reading") or assets.get("idle", "")
        if state == "file_catch":
            return assets.get("file_catch") or assets.get("happy") or assets.get("idle", "")
        if state == "idle":
            if self._is_hungry and assets.get("hungry"):
                return assets["hungry"]
            if self._idle_submode == "guitar" and assets.get("practice_guitar"):
                return assets["practice_guitar"]
            if self._idle_submode == "tea" and assets.get("tea"):
                return assets["tea"]
            if self._idle_submode == "stretch" and assets.get("stretch"):
                return assets["stretch"]
            if self._idle_submode == "study" and assets.get("study_desk"):
                return assets["study_desk"]
            if self._idle_submode == "sit_swing" and assets.get("sit_swing"):
                return assets["sit_swing"]
            if self._idle_submode == "music_dance" and assets.get("music_dance"):
                return assets["music_dance"]
            if (t % 3.4) > 3.26 and assets.get("idle_blink"):
                return assets["idle_blink"]
            return assets.get("idle", "")
        return assets.get(state) or assets.get("idle", "")

    def _reload_media_for_state(self, state: str) -> None:
        if not self._skin.get("has_custom_images"):
            self._stop_movie()
            self._current_asset_path = ""
            return
        path = self._pick_asset_for_current_frame(state, time.perf_counter() - self._start_time)
        self._load_asset_path(path)

    def _load_asset_path(self, path: str) -> None:
        if path == self._current_asset_path:
            return
        self._current_asset_path = path
        self._stop_movie()
        if not path or not Path(path).is_file():
            return
        if path.lower().endswith(".gif"):
            movie = QMovie(path)
            movie.frameChanged.connect(self.update)
            movie.start()
            self._movie = movie
        else:
            if path not in self._pixmap_cache:
                self._pixmap_cache[path] = QPixmap(path)

    def _stop_movie(self) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
            self._movie = None

    def _on_tick(self) -> None:
        now = time.perf_counter()

        # 推进多文件“一口一口吃掉”动画队列
        if self._state == "eating":
            if not self._eat_queue:
                self._state = "happy"
                self._state_reset_at = now + 3.0
                if self._eat_recycled > 0:
                    msg = f"已吃掉 {self._eat_recycled} 个文件并送进回收站"
                else:
                    msg = f"全部 {self._eat_total} 个都吃光啦" if self._eat_total > 1 else "吃掉啦，真好吃"
                self.show_bubble(msg, duration=3.5)
                if self._eat_total > 0:
                    self.files_eaten_completed.emit(self._eat_total)
            else:
                elapsed = now - self._eat_item_start
                if elapsed >= self._eat_duration_per_item:
                    eaten_path, _, _ = self._eat_queue.pop(0)
                    if self._settings.get("eat_moves_to_recycle_bin", False):
                        if _move_to_recycle_bin(eaten_path):
                            self._eat_recycled += 1
                    self._eat_index += 1
                    self._eat_item_start = now
                    if self._eat_queue:
                        fname = self._eat_queue[0][1]
                        short = fname[:10] + ("..." if len(fname) > 10 else "")
                        self.show_bubble(f"正在吃 ({self._eat_index + 1}/{self._eat_total}) {short}", duration=2.3)

        # 桌面自由散步推进
        if self._state in ("walk_left", "walk_right") and not self._dragging and self._walk_dir != 0:
            dt = max(0.0, min(0.08, now - self._walk_last_tick))
            self._walk_last_tick = now
            self._walk_accum_x += self._walk_dir * self._walk_speed * dt
            step_x = int(self._walk_accum_x)
            if step_x != 0:
                self._walk_accum_x -= step_x
                screen = QApplication.primaryScreen()
                if screen:
                    avail = screen.availableGeometry()
                    nx = self.x() + step_x
                    min_x = avail.left() + 18
                    max_x = avail.right() - self.width() - 18
                    if nx <= min_x:
                        nx = min_x
                        self._walk_dir = 1
                        self._state = "walk_right"
                    elif nx >= max_x:
                        nx = max_x
                        self._walk_dir = -1
                        self._state = "walk_left"
                    self.move(nx, self.y())
                    self.moved.emit()
            if self._walk_until and now >= self._walk_until:
                self._walk_dir = 0
                self._walk_until = 0.0
                if random.random() < 0.45:
                    self._state = "sit_swing"
                    self._state_reset_at = now + 4.0
                else:
                    self._state = "idle"
                    self._state_reset_at = 0.0

        if self._state_reset_at and now >= self._state_reset_at:
            self._state_reset_at = 0.0
            self._walk_dir = 0
            self._state = f"peek_{self._edge_side}" if self._edge_side else "idle"

        sleep_min = max(0, min(120, int(self._settings.get("pet_sleep_timeout_min", 10) or 0)))
        if sleep_min > 0 and self._state == "idle" and now - self._last_interaction > sleep_min * 60:
            self._state = "sleep"
            lines = (self._skin.get("bubbles") or {}).get("sleep") or []
            if lines and self._settings.get("pet_idle_bubbles", True):
                self.show_bubble(random.choice(lines))

        if self._bubble_text and now > self._bubble_until:
            self._bubble_text = ""

        if self._skin.get("has_custom_images"):
            t = now - self._start_time
            desired = self._pick_asset_for_current_frame(self._state, t)
            if desired != self._current_asset_path:
                self._load_asset_path(desired)

        self._drag_vx *= 0.84
        self.update()

    def _start_stroll(self, direction: int | None = None, duration: float | None = None) -> None:
        """启动桌面自由散步动作."""
        now = time.perf_counter()
        if direction is None:
            screen = QApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                if self.x() < avail.left() + avail.width() * 0.22:
                    direction = 1
                elif self.x() > avail.right() - avail.width() * 0.28:
                    direction = -1
                else:
                    direction = random.choice([-1, 1])
            else:
                direction = random.choice([-1, 1])
        self._edge_side = None
        self._walk_dir = -1 if direction < 0 else 1
        self._state = "walk_left" if self._walk_dir < 0 else "walk_right"
        base_dur = float(max(2, min(15, int(self._settings.get("pet_walk_duration_sec", 4) or 4))))
        dur = duration if duration is not None else random.uniform(max(2.0, base_dur * 0.75), base_dur * 1.25)
        self._walk_until = now + dur
        self._state_reset_at = self._walk_until + 0.1
        self._walk_last_tick = now
        self._walk_accum_x = 0.0
        self._idle_submode = "normal"
        self._reload_media_for_state(self._state)

    def _on_idle_director(self) -> None:
        if self._state != "idle" or self._dragging:
            return
        if self._drop_choice_dock is not None and self._drop_choice_dock.isVisible():
            return
        roll = random.random()
        if (
            self._settings.get("pet_auto_walk", True)
            and self._edge_side is None
            and not self._is_hungry
            and roll < 0.22
        ):
            self._start_stroll()
            return
        if roll < 0.36:
            self._idle_submode = "sit_swing"
        elif roll < 0.50:
            self._idle_submode = "music_dance"
        elif roll < 0.64:
            self._idle_submode = "guitar"
        elif roll < 0.76:
            self._idle_submode = "tea"
        elif roll < 0.85:
            self._idle_submode = "stretch"
        elif roll < 0.92:
            self._idle_submode = "study"
        else:
            self._idle_submode = "normal"

        if self._settings.get("pet_idle_bubbles", True) and not self._bubble_text and random.random() < 0.28:
            lines = (self._skin.get("bubbles") or {}).get("idle") or []
            if lines:
                self.show_bubble(random.choice(lines), duration=3.8)

    def _pet_draw_rect(self) -> QRectF:
        pet_sz = float(self._pet_box_size())
        x = (self.width() - pet_sz) / 2.0
        y = self.height() - pet_sz - 6.0
        return QRectF(x, y, pet_sz, pet_sz)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        t = time.perf_counter() - self._start_time
        pet_rect = self._pet_draw_rect()

        if self._skin.get("has_custom_images") and self._current_asset_path:
            self._paint_anime_sprite(painter, pet_rect, t)
        else:
            cursor_local = self.mapFromGlobal(QCursor.pos())
            center = pet_rect.center()
            dx = (cursor_local.x() - center.x()) / max(1.0, pet_rect.width())
            dy = (cursor_local.y() - center.y()) / max(1.0, pet_rect.height())
            self._renderer.draw(
                painter=painter,
                rect=pet_rect,
                state=self._state,
                t=t,
                idle_submode=self._idle_submode,
                look_x=dx,
                look_y=dy,
                drag_vx=self._drag_vx,
            )

        if self._bubble_text:
            self._paint_bubble(painter)

    def _paint_anime_sprite(self, painter: QPainter, pet_rect: QRectF, t: float) -> None:
        pix = (
            self._movie.currentPixmap()
            if self._movie is not None
            else self._pixmap_cache.get(self._current_asset_path)
        )
        if not pix or pix.isNull():
            self._renderer.draw(painter, pet_rect, self._state, t, self._idle_submode)
            return

        dy = math.sin(t * 2.5) * 2.0
        dx = 0.0
        scale_x = 1.0 - math.sin(t * 2.5) * 0.011
        scale_y = 1.0 + math.sin(t * 2.5) * 0.015
        rot = 0.0

        if self._state == "drag":
            rot = max(-18.0, min(18.0, -self._drag_vx * 0.55 + math.sin(t * 9.0) * 6.0))
            dy = -5.0
        elif self._state == "happy":
            hop = abs(math.sin(t * 6.8))
            dy = -hop * 14.0
            rot = math.sin(t * 6.8) * 4.5
        elif self._state == "file_catch":
            dy = -3.0 + math.sin(t * 6.5) * 2.5
            scale_y = 1.0 + math.sin(t * 6.5) * 0.024
        elif self._state == "eating":
            chomp = math.sin(t * 11.0)
            dy = -abs(chomp) * 3.5
            rot = chomp * 2.5
            scale_x = 1.0 + chomp * 0.025
            scale_y = 1.0 - chomp * 0.02
        elif self._state == "inspect_file":
            rot = math.sin(t * 3.4) * 3.5
            dy = math.sin(t * 3.4) * 1.8
        elif self._state == "speaking" or self._state == "practice_guitar" or (self._state == "idle" and self._idle_submode == "guitar"):
            rot = math.sin(t * 5.2) * 3.8
            dy = -abs(math.sin(t * 5.2)) * 3.8
        elif self._state == "pet_head":
            # 享受摸头：温柔左右蹭头 + 软弹起伏
            rot = math.sin(t * 5.5) * 4.5
            scale_y = 1.0 - abs(math.sin(t * 5.5)) * 0.032
            scale_x = 1.0 + abs(math.sin(t * 5.5)) * 0.025
        elif self._state == "eat_cake":
            dy = -abs(math.sin(t * 6.0)) * 4.2
            rot = math.sin(t * 6.0) * 3.0
        elif self._state == "study_desk":
            rot = math.sin(t * 2.2) * 2.2
            dy = math.sin(t * 2.2) * 1.4
        elif self._state == "hungry":
            dy = math.sin(t * 2.0) * 1.6
            rot = math.sin(t * 3.0) * 2.5
        elif self._state == "stretch":
            stretch_p = abs(math.sin(t * 2.6))
            scale_y = 1.0 + stretch_p * 0.045
            scale_x = 1.0 - stretch_p * 0.02
            dy = -stretch_p * 5.0
        elif self._state in ("walk_left", "walk_right"):
            step = math.sin(t * 8.0)
            dy = -abs(step) * 5.2
            rot = step * 3.8
            scale_y = 1.0 - abs(step) * 0.018
        elif self._state == "sit_swing" or (self._state == "idle" and self._idle_submode == "sit_swing"):
            rot = math.sin(t * 2.5) * 3.0
            dy = math.sin(t * 5.0) * 1.4
        elif self._state == "music_dance" or (self._state == "idle" and self._idle_submode == "music_dance"):
            beat = math.sin(t * 6.4)
            dy = -abs(beat) * 6.0
            rot = math.sin(t * 3.2) * 6.2
            scale_y = 1.0 - abs(beat) * 0.025
            scale_x = 1.0 + abs(beat) * 0.02
        elif self._state == "shy_blush":
            dx = math.sin(t * 7.5) * 1.6
            rot = math.sin(t * 3.8) * 3.0
            scale_y = 1.0 - abs(math.sin(t * 3.8)) * 0.02
        elif self._state == "proud_pose":
            puff = abs(math.sin(t * 3.6))
            dy = -puff * 3.5
            scale_y = 1.0 + puff * 0.024
            rot = math.sin(t * 2.4) * 2.2
        elif self._state == "thinking":
            rot = 3.5 + math.sin(t * 1.8) * 1.8
        elif self._state == "searching":
            rot = math.sin(t * 3.2) * 4.0
        elif self._state == "error":
            dx = math.sin(t * 34.0) * 2.4
        elif self._state == "sleep":
            dy = math.sin(t * 1.3) * 1.8
            scale_y = 1.0 + math.sin(t * 1.3) * 0.022
        elif self._state in ("peek_left", "peek_right"):
            dy = math.sin(t * 2.2) * 3.0
            rot = math.sin(t * 1.8) * (3.2 if self._state == "peek_right" else -3.2)
            scale_x = 1.0
            scale_y = 1.0 + math.sin(t * 2.2) * 0.012
        elif self._state == "hover":
            dy = -3.0 + math.sin(t * 4.5) * 2.0

        # 底部柔和阴影 / 接文件提示光环（扒在屏幕边缘和拖拽时不画地面阴影）
        if self._state == "file_catch":
            pulse = 1.0 + math.sin(t * 7.5) * 0.07
            painter.setPen(QPen(QColor(229, 107, 77, 195), 2.0, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(255, 214, 170, 65))
            painter.drawEllipse(QPointF(pet_rect.center().x(), pet_rect.bottom() - 8), 45 * pulse, 11 * pulse)
        elif self._state not in ("drag", "peek_left", "peek_right"):
            shrink = max(0.6, 1.0 + dy * 0.02)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(35, 25, 20, 38))
            painter.drawEllipse(QPointF(pet_rect.center().x(), pet_rect.bottom() - 5), 34 * shrink, 7 * shrink)

        target_w = int(pet_rect.width() * 0.94)
        target_h = int(pet_rect.height() * 0.94)
        scaled = pix.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # 扒在屏幕左右边缘时贴紧对应边缘，显得真正抓着屏幕边框探头偷看
        if self._state == "peek_right":
            cx = self.width() - scaled.width() / 2.0
            cy = pet_rect.center().y() + dy
        elif self._state == "peek_left":
            cx = scaled.width() / 2.0
            cy = pet_rect.center().y() + dy
        else:
            cx = pet_rect.center().x() + dx
            cy = pet_rect.bottom() - scaled.height() / 2.0 - 6.0 + dy

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(rot)
        painter.scale(scale_x, scale_y)
        painter.drawPixmap(int(-scaled.width() / 2), int(-scaled.height() / 2), scaled)
        painter.restore()

        # 吃掉动画：在空手双掌正中绘制真实文件图标，逐口啃出牙印缺口并飞出碎屑
        if self._state == "eating" and self._eat_queue:
            self._paint_eating_file_icon(painter, cx, cy, scaled.width(), scaled.height(), t)
        # 读取研究动画：在伸出的右掌心上稳稳托着真实文件图标（多文件呈扇形叠放）
        elif (self._state in ("inspect_file", "reading")) and self._inspect_icons:
            self._paint_inspecting_file_icon(painter, cx, cy, scaled.width(), scaled.height(), t)

    def _make_bitten_pixmap(self, pix: QPixmap, bite_stage: int) -> QPixmap:
        """根据啃咬阶段 (0/1/2/3) 从顶部中央对称抠出清晰的月牙形牙印缺口，保证卡片始终居中夹在双手中."""
        w, h = pix.width(), pix.height()
        result = QPixmap(w, h)
        result.fill(Qt.GlobalColor.transparent)
        p = QPainter(result)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.drawPixmap(0, 0, pix)
        if bite_stage >= 1:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(Qt.GlobalColor.transparent)
            # 第 1 口：对称咬掉顶部中央一大口（三联弧形牙印）
            if bite_stage >= 1:
                p.drawEllipse(QPointF(w * 0.50, h * 0.06), w * 0.28, h * 0.25)
                p.drawEllipse(QPointF(w * 0.28, h * 0.08), w * 0.19, h * 0.18)
                p.drawEllipse(QPointF(w * 0.72, h * 0.08), w * 0.19, h * 0.18)
            # 第 2 口：对称啃掉上半张文件卡片，留出波浪形咬痕
            if bite_stage >= 2:
                p.drawRect(QRectF(0, 0, w, h * 0.34))
                p.drawEllipse(QPointF(w * 0.24, h * 0.36), w * 0.22, h * 0.19)
                p.drawEllipse(QPointF(w * 0.50, h * 0.42), w * 0.26, h * 0.22)
                p.drawEllipse(QPointF(w * 0.76, h * 0.36), w * 0.22, h * 0.19)
            # 第 3 口：只剩底部一小截卡片准备最后一口吞掉
            if bite_stage >= 3:
                p.drawRect(QRectF(0, 0, w, h * 0.64))
                p.drawEllipse(QPointF(w * 0.30, h * 0.66), w * 0.22, h * 0.18)
                p.drawEllipse(QPointF(w * 0.70, h * 0.66), w * 0.22, h * 0.18)
        p.end()
        return result

    def _paint_eating_file_icon(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        char_w: int,
        char_h: int,
        t: float,
    ) -> None:
        _, _, icon_pix = self._eat_queue[0]
        if icon_pix.isNull():
            return
        elapsed = max(0.0, time.perf_counter() - self._eat_item_start)
        progress = min(1.0, elapsed / self._eat_duration_per_item)
        if progress < 0.22:
            bite_stage = 0
            fade = 1.0
        elif progress < 0.52:
            bite_stage = 1
            fade = 1.0
        elif progress < 0.80:
            bite_stage = 2
            fade = 1.0
        elif progress < 0.94:
            bite_stage = 3
            fade = 1.0
        else:
            bite_stage = 3
            fade = max(0.0, (1.0 - progress) / 0.06)

        if fade <= 0.02:
            return

        icon_sz = max(32, int(char_h * 0.215))
        base_scaled = icon_pix.scaled(
            icon_sz,
            icon_sz,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        bitten = self._make_bitten_pixmap(base_scaled, bite_stage)

        # 严格居中夹在左右两只举起的小手正中，刚好在张开的小嘴下方，不挡脸且双手清晰可见
        anchors = (self._skin.get("file_anchors") or {}) if isinstance(self._skin, dict) else {}
        eat_x_ratio = float(anchors.get("eat_x", 0.0))
        eat_y_ratio = float(anchors.get("eat_y", 0.068))
        phase = int(elapsed / 0.34) % 2
        chomp = math.sin(t * 11.0)
        mouth_lift = (4.5 if phase == 0 else 1.0) + max(0.0, chomp) * 2.5
        if bite_stage == 3:
            mouth_lift += 4.0
        ix = cx + char_w * eat_x_ratio - bitten.width() / 2.0
        iy = cy + char_h * eat_y_ratio - bitten.height() / 2.0 - mouth_lift

        painter.save()
        painter.setOpacity(fade)
        painter.drawPixmap(int(ix), int(iy), bitten)

        # 每次啃咬飞出彩色小碎屑 + 漫画拟声词（咔嚓 / 嚼嚼）
        cycle = elapsed % 0.68
        if bite_stage >= 1 and cycle < 0.38:
            sub_p = cycle / 0.38
            painter.setPen(Qt.PenStyle.NoPen)
            for vx, vy, col in [
                (-24, -18, "#FFD166"),
                (24, -16, "#FF9F43"),
                (-16, 12, "#FFF3DC"),
                (18, 11, "#FF7A59"),
                (-8, -22, "#74C0FC"),
                (10, -20, "#69DB7C"),
            ]:
                c = QColor(col)
                c.setAlpha(int((1.0 - sub_p) * 240))
                painter.setBrush(c)
                painter.drawEllipse(
                    QPointF(cx + vx * sub_p, iy + bitten.height() * 0.25 + vy * sub_p + sub_p * sub_p * 15),
                    2.8,
                    2.8,
                )
            # 漫画小拟声字
            pop_words = ["咔嚓", "啊呜", "嚼嚼"]
            word = pop_words[min(len(pop_words) - 1, bite_stage - 1)]
            alpha = int((1.0 - sub_p) * 245)
            side = 1 if bite_stage % 2 == 1 else -1
            tx = cx + side * (char_w * 0.24)
            ty = cy - char_h * 0.06 - sub_p * 12.0
            painter.setFont(QFont("Microsoft YaHei UI", 8, QFont.Weight.Bold))
            painter.setPen(QColor(255, 255, 255, alpha))
            painter.drawText(QRectF(tx - 21, ty - 11, 44, 20), Qt.AlignmentFlag.AlignCenter, word)
            painter.setPen(QColor(229, 107, 77, alpha))
            painter.drawText(QRectF(tx - 22, ty - 12, 44, 20), Qt.AlignmentFlag.AlignCenter, word)
        painter.restore()

    def _paint_inspecting_file_icon(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        char_w: int,
        char_h: int,
        t: float,
    ) -> None:
        if not self._inspect_icons:
            return
        sz = max(38, int(char_h * 0.255))
        bob = math.sin(t * 3.4) * 2.0
        # 精准对齐伸出的右侧托掌掌面（支持按皮肤自定义掌心坐标）
        anchors = (self._skin.get("file_anchors") or {}) if isinstance(self._skin, dict) else {}
        palm_x_ratio = float(anchors.get("inspect_x", 0.195))
        palm_y_ratio = float(anchors.get("inspect_y", 0.048))
        palm_x = cx + char_w * palm_x_ratio
        palm_y = cy + char_h * palm_y_ratio + bob
        card_cy = palm_y - sz * 0.44

        # 多文件时最多扇形叠放展示 3 张清晰文件卡片，最前面的带扫描光效
        show_items = self._inspect_icons[:3]
        painter.save()
        for rev_idx in range(len(show_items) - 1, -1, -1):
            _, icon_pix = show_items[rev_idx]
            if icon_pix.isNull():
                continue
            icon_scaled = icon_pix.scaled(
                sz,
                sz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            offset_x = rev_idx * 5.5
            offset_y = -rev_idx * 4.5
            angle = -6.0 + rev_idx * 10.0
            painter.save()
            painter.translate(palm_x + offset_x, card_cy + offset_y)
            painter.rotate(angle)
            iw, ih = icon_scaled.width(), icon_scaled.height()
            painter.drawPixmap(int(-iw / 2), int(-ih / 2), icon_scaled)

            # 最前面的文件卡增加柔和扫描光带，呈现正在用放大镜细读的效果
            if rev_idx == 0:
                sweep = ((t * 0.9) % 1.4) - 0.2
                if 0.0 <= sweep <= 1.0:
                    scan_y = -ih / 2.0 + sweep * ih
                    grad = QLinearGradient(0, scan_y - 6, 0, scan_y + 6)
                    grad.setColorAt(0.0, QColor(255, 255, 255, 0))
                    grad.setColorAt(0.5, QColor(255, 232, 180, 155))
                    grad.setColorAt(1.0, QColor(255, 255, 255, 0))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(grad)
                    painter.drawRoundedRect(QRectF(-iw * 0.44, scan_y - 5, iw * 0.88, 10), 3, 3)
            painter.restore()

        if len(self._inspect_icons) > 1:
            bx = palm_x + sz * 0.48
            by = card_cy - sz * 0.45
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#E56B4D"))
            painter.drawEllipse(QPointF(bx, by), 9.5, 9.5)
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont("Microsoft YaHei UI", 8, QFont.Weight.Bold))
            painter.drawText(QRectF(bx - 10, by - 10, 20, 20), Qt.AlignmentFlag.AlignCenter, str(len(self._inspect_icons)))
        painter.restore()

    def _paint_bubble(self, painter: QPainter) -> None:
        font = QFont("Microsoft YaHei UI", 9)
        painter.setFont(font)
        fm = painter.fontMetrics()
        max_w = self.width() - 12
        text_rect = fm.boundingRect(
            QRect(0, 0, max_w - 18, 42),
            Qt.TextFlag.TextWordWrap,
            self._bubble_text,
        )
        bw = min(max_w, max(80, text_rect.width() + 20))
        bh = min(44, text_rect.height() + 10)
        bx = (self.width() - bw) / 2.0
        by = 4.0

        box = QRectF(bx, by, bw, bh)
        painter.setPen(QPen(QColor(229, 107, 77, 130), 1.1))
        painter.setBrush(QColor(255, 253, 250, 246))
        painter.drawRoundedRect(box, 10, 10)
        painter.setPen(QColor("#2B2F36"))
        painter.drawText(
            box.adjusted(8, 4, -8, -4),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            self._bubble_text,
        )

    # ---------- 鼠标与悬停 ----------

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._hide_dock_timer.stop()
        self._last_interaction = time.perf_counter()
        if self._drop_choice_dock is not None and self._drop_choice_dock.isVisible():
            return
        if self._state in ("idle", "sleep", "walk_left", "walk_right"):
            self._walk_dir = 0
            self._state = "hover"
        self._layout_docks()
        if self._dock is not None and self._state not in ("eating", "inspect_file"):
            self._dock.show()
        self.update()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hide_dock_timer.start()

    def _hide_dock_if_outside(self) -> None:
        if self._dock is None:
            return
        local_pos = self.mapFromGlobal(QCursor.pos())
        if self._dock.isVisible() and self._dock.geometry().adjusted(-8, -8, 8, 12).contains(local_pos):
            return
        if self._pet_draw_rect().contains(QPointF(local_pos)):
            return
        self._dock.hide()
        if self._state == "hover":
            self._state = f"peek_{self._edge_side}" if self._edge_side else "idle"
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self._last_interaction = time.perf_counter()
        self._walk_dir = 0
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_moved = False
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._last_drag_x = event.globalPosition().toPoint().x()
        elif event.button() == Qt.MouseButton.RightButton:
            if self._dock is not None:
                self._dock.hide()
            self._show_context_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._dragging and (event.buttons() & Qt.MouseButton.LeftButton):
            gpos = event.globalPosition().toPoint()
            new_pos = gpos - self._drag_offset
            if (new_pos - self.pos()).manhattanLength() > 4:
                self._drag_moved = True
                if self._dock is not None:
                    self._dock.hide()
                if self._drop_choice_dock is not None and self._drop_choice_dock.isVisible():
                    self._cancel_drop_choice()
                if self._state != "drag":
                    self._state = "drag"
                    self._edge_side = None
            self._drag_vx = float(gpos.x() - self._last_drag_x)
            self._last_drag_x = gpos.x()
            self.move(new_pos)
            self.moved.emit()
            return

        # 无按键时，在桌宠头顶区域左右轻轻来回摩擦即可触发「摸摸头」养成互动
        now = time.perf_counter()
        if now >= self._pat_cooldown_until and self._state in ("idle", "hover", "hungry"):
            pos = event.position()
            pet_rect = self._pet_draw_rect()
            head_rect = QRectF(pet_rect.left() + pet_rect.width() * 0.18, pet_rect.top(), pet_rect.width() * 0.64, pet_rect.height() * 0.44)
            if head_rect.contains(pos):
                dx = pos.x() - self._pat_last_x
                if abs(dx) >= 6.0:
                    cur_dir = 1 if dx > 0 else -1
                    if now - self._pat_window_start > 1.5:
                        self._pat_window_start = now
                        self._pat_flips = 0
                    if self._pat_last_dir != 0 and cur_dir != self._pat_last_dir:
                        self._pat_flips += 1
                    self._pat_last_dir = cur_dir
                    self._pat_last_x = pos.x()
                    if self._pat_flips >= 3:
                        self._pat_flips = 0
                        self._pat_cooldown_until = now + 5.0
                        self.head_patted.emit()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            if self._drag_moved:
                if not self._snap_edge_if_needed():
                    self._edge_side = None
                    self._state = "idle"
            else:
                if self._drop_choice_dock is not None and self._drop_choice_dock.isVisible():
                    return
                self.clicked_chat.emit()

    def _snap_edge_if_needed(self) -> bool:
        """拖到屏幕左/右边缘松手时，自动贴边扒在屏幕边缘探头偷看."""
        if not self._settings.get("pet_edge_hide", True):
            return False
        screen = QApplication.primaryScreen()
        if not screen:
            return False
        avail = screen.availableGeometry()
        pet_left = self.x() + int(self._pet_draw_rect().left())
        pet_right = self.x() + int(self._pet_draw_rect().right())

        if pet_left <= avail.left() + 34:
            self.move(avail.left(), self.y())
            self._edge_side = "left"
            self._state = "peek_left"
            self.show_bubble("偷偷看你", duration=2.4)
            self.moved.emit()
            return True
        if pet_right >= avail.right() - 34:
            self.move(avail.right() - self.width() + 1, self.y())
            self._edge_side = "right"
            self._state = "peek_right"
            self.show_bubble("偷偷看你", duration=2.4)
            self.moved.emit()
            return True
        return False

    # ---------- 多文件拖拽交互：仰头张嘴 -> 松手出现「吃掉 / 读取」 ----------

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            urls = [u for u in event.mimeData().urls() if u.isLocalFile()]
            if not urls:
                return
            event.acceptProposedAction()
            if self._dock is not None:
                self._dock.hide()
            if self._drop_choice_dock is not None:
                self._drop_choice_dock.hide()
            self._state = "file_catch"
            tip = f"啊— 准备接住 {len(urls)} 个文件" if len(urls) > 1 else "啊— 松手给我吧"
            self.show_bubble(tip, duration=4.0)

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        if self._state == "file_catch":
            self._state = "idle"
            self._bubble_text = ""
            self.update()

    def _trim_transparent_pixmap(self, pix: QPixmap) -> QPixmap:
        """裁掉 Windows 系统图标四周多余的透明留白，防止小尺寸图标缩成模糊小白点."""
        if pix.isNull():
            return pix
        img = pix.toImage().convertToFormat(pix.toImage().Format.Format_ARGB32)
        w, h = img.width(), img.height()
        min_x, min_y, max_x, max_y = w, h, -1, -1
        for y in range(h):
            for x in range(w):
                if img.pixelColor(x, y).alpha() > 16:
                    if x < min_x:
                        min_x = x
                    if y < min_y:
                        min_y = y
                    if x > max_x:
                        max_x = x
                    if y > max_y:
                        max_y = y
        if max_x < min_x or max_y < min_y:
            return pix
        return pix.copy(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)

    def _load_real_file_icon(self, file_path: str) -> QPixmap:
        """生成清晰精致的 72x72 文件卡片图标：图片显示圆角缩略图，文档/代码合成真实系统图标+彩色格式角标."""
        p = Path(file_path)
        ext = p.suffix.lower().lstrip(".")
        if ext in ("png", "jpg", "jpeg", "webp", "bmp", "gif"):
            raw = QPixmap(file_path)
            if not raw.isNull():
                thumb = raw.scaled(
                    62, 62, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
                )
                cx = max(0, (thumb.width() - 62) // 2)
                cy = max(0, (thumb.height() - 62) // 2)
                cropped = thumb.copy(cx, cy, 62, 62)
                card = QPixmap(72, 72)
                card.fill(Qt.GlobalColor.transparent)
                pt = QPainter(card)
                pt.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                pt.setPen(Qt.PenStyle.NoPen)
                pt.setBrush(QColor(25, 22, 20, 48))
                pt.drawRoundedRect(QRectF(6, 7, 62, 62), 10, 10)
                path = QPainterPath()
                path.addRoundedRect(QRectF(4, 4, 62, 62), 10, 10)
                pt.setPen(QPen(QColor("#FFFFFF"), 2.6))
                pt.setBrush(QColor("#FFFFFF"))
                pt.drawPath(path)
                pt.setClipPath(path)
                pt.drawPixmap(4, 4, cropped)
                pt.end()
                return card

        # 颜色区分常见文件格式，卡片辨识度极高（告别 16px 小白块）
        badge_colors = {
            "doc": "#2B6CB0",
            "docx": "#2B6CB0",
            "xls": "#1E8E5A",
            "xlsx": "#1E8E5A",
            "csv": "#1E8E5A",
            "pdf": "#D9483B",
            "ppt": "#D96B27",
            "pptx": "#D96B27",
            "txt": "#5B6678",
            "md": "#4A5568",
            "json": "#6B5CE7",
            "py": "#3776AB",
            "js": "#C98A00",
            "ts": "#2F74C0",
            "html": "#E05A2B",
            "css": "#2965F1",
            "zip": "#B7791F",
            "rar": "#B7791F",
            "7z": "#B7791F",
            "mp3": "#C2418A",
            "wav": "#C2418A",
            "mp4": "#7C3AED",
        }
        accent = QColor(badge_colors.get(ext, "#E56B4D"))
        label = (ext.upper()[:4] if ext else "FILE")

        card = QPixmap(72, 72)
        card.fill(Qt.GlobalColor.transparent)
        pt = QPainter(card)
        pt.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pt.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # 柔和阴影
        pt.setPen(Qt.PenStyle.NoPen)
        pt.setBrush(QColor(25, 22, 20, 48))
        pt.drawRoundedRect(QRectF(10, 7, 54, 62), 9, 9)

        # 圆角暖白文件卡片主体
        body = QRectF(8, 4, 54, 62)
        pt.setPen(QPen(QColor("#D6CFC6"), 1.6))
        pt.setBrush(QColor("#FFFDF9"))
        pt.drawRoundedRect(body, 9, 9)

        # 右上角精致折角装饰
        fold = QPainterPath()
        fold.moveTo(49, 4)
        fold.lineTo(62, 17)
        fold.lineTo(49, 17)
        fold.closeSubpath()
        pt.setPen(Qt.PenStyle.NoPen)
        pt.setBrush(QColor("#EAE2D7"))
        pt.drawPath(fold)

        # 顶部偏中放置裁去留白后的真实 Windows 系统图标
        qicon = self._icon_provider.icon(QFileInfo(file_path))
        sys_pix = self._trim_transparent_pixmap(qicon.pixmap(64, 64))
        if not sys_pix.isNull():
            icon_s = sys_pix.scaled(
                28, 28, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            pt.drawPixmap(int(body.center().x() - icon_s.width() / 2.0), int(12 + (28 - icon_s.height()) / 2.0), icon_s)

        # 底部彩色格式徽章条（清晰显示 DOCX / XLSX / PDF / TXT 等）
        tag_rect = QRectF(12, 45, 46, 17)
        pt.setPen(Qt.PenStyle.NoPen)
        pt.setBrush(accent)
        pt.drawRoundedRect(tag_rect, 5, 5)
        pt.setPen(QColor("#FFFFFF"))
        pt.setFont(QFont("Microsoft YaHei UI", 8, QFont.Weight.Bold))
        pt.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, label)
        pt.end()
        return card

    def dropEvent(self, event) -> None:  # type: ignore[override]
        urls = event.mimeData().urls()
        paths = [u.toLocalFile() for u in urls if u.isLocalFile() and Path(u.toLocalFile()).is_file()]
        if not paths:
            self._state = "idle"
            return

        self._pending_drop_paths = paths
        self._pending_drop_icons = []
        for p in paths:
            self._pending_drop_icons.append((Path(p).name, self._load_real_file_icon(p)))

        if self._dock is not None:
            self._dock.hide()
        self._state = "file_catch"
        self._layout_docks()
        if self._drop_choice_dock is not None:
            self._drop_choice_dock.show()
            self._drop_choice_dock.raise_()
        tip = f"收到 {len(paths)} 个文件，要吃掉还是读取？" if len(paths) > 1 else f"收到 {Path(paths[0]).name[:12]}"
        self.show_bubble(tip, duration=15.0)

    def _on_choose_eat(self) -> None:
        if self._drop_choice_dock is not None:
            self._drop_choice_dock.hide()
        if not self._pending_drop_icons:
            self._state = "idle"
            return
        self._eat_queue = [
            (self._pending_drop_paths[i] if i < len(self._pending_drop_paths) else "", name, pix)
            for i, (name, pix) in enumerate(self._pending_drop_icons)
        ]
        self._eat_total = len(self._eat_queue)
        self._eat_index = 0
        self._eat_recycled = 0
        self._eat_item_start = time.perf_counter()
        self._pending_drop_paths = []
        self._pending_drop_icons = []
        self._state = "eating"
        fname = self._eat_queue[0][1]
        short = fname[:10] + ("..." if len(fname) > 10 else "")
        tip = f"开吃啦 (1/{self._eat_total}) {short}" if self._eat_total > 1 else f"一口一口吃掉 {short}"
        self.show_bubble(tip, duration=2.3)

    def _on_choose_read(self) -> None:
        if self._drop_choice_dock is not None:
            self._drop_choice_dock.hide()
        paths = list(self._pending_drop_paths)
        self._inspect_icons = list(self._pending_drop_icons)
        self._pending_drop_paths = []
        self._pending_drop_icons = []
        if not paths:
            self._state = "idle"
            return
        self._state = "inspect_file"
        tip = f"拿着放大镜研究 {len(paths)} 个文件..." if len(paths) > 1 else f"正在研究 {Path(paths[0]).name[:12]}..."
        self.show_bubble(tip, duration=8.0)
        self.files_read_requested.emit(paths)

    def _cancel_drop_choice(self) -> None:
        if self._drop_choice_dock is not None:
            self._drop_choice_dock.hide()
        self._pending_drop_paths = []
        self._pending_drop_icons = []
        self._bubble_text = ""
        self._state = "idle"
        self.update()

    # ---------- 极简右键菜单 ----------

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu {
                background: #FFFFFF;
                border: 1px solid #E5DFD6;
                border-radius: 9px;
                padding: 5px;
                font-family: "Microsoft YaHei UI";
                font-size: 12.5px;
            }
            QMenu::item { padding: 6px 18px; border-radius: 6px; color: #1F2328; }
            QMenu::item:selected { background: #FDF0EC; color: #E56B4D; }
            """
        )

        a_chat = QAction("打开对话", self)
        a_chat.triggered.connect(lambda: self.clicked_chat.emit())
        menu.addAction(a_chat)

        a_care = QAction("桌宠养成", self)
        a_care.triggered.connect(lambda: self.care_triggered.emit())
        menu.addAction(a_care)

        a_new = QAction("开启新对话", self)
        a_new.triggered.connect(lambda: self.new_chat_triggered.emit())
        menu.addAction(a_new)

        a_web = QAction("联网搜索", self)
        a_web.setCheckable(True)
        a_web.setChecked(bool(self._settings.get("web_search_enabled", False)))
        a_web.toggled.connect(lambda checked: self.web_search_toggled.emit(bool(checked)))
        menu.addAction(a_web)

        a_walk = QAction("桌面自由漫游", self)
        a_walk.setCheckable(True)
        a_walk.setChecked(bool(self._settings.get("pet_auto_walk", True)))
        a_walk.toggled.connect(lambda checked: self.auto_walk_toggled.emit(bool(checked)))
        menu.addAction(a_walk)

        skins_menu = menu.addMenu("切换角色形象")
        active_skin_id = str(self._settings.get("active_skin_id") or "default_sprite")
        for s in list_skins():
            if not s.get("has_custom_images") and s["id"] == "yui_template":
                continue
            a_skin = QAction(str(s.get("name") or s["id"]), self)
            a_skin.setCheckable(True)
            a_skin.setChecked(s["id"] == active_skin_id)
            a_skin.triggered.connect(lambda _=False, sid=s["id"]: self.skin_selected.emit(sid))
            skins_menu.addAction(a_skin)

        clip_menu = menu.addMenu("剪贴板快捷处理")
        for label, cmd in [
            ("翻译剪贴板", "translate"),
            ("总结剪贴板", "summarize"),
            ("解释剪贴板代码", "explain"),
        ]:
            a = QAction(label, self)
            a.triggered.connect(lambda _=False, c=cmd: self.clipboard_action.emit(c))
            clip_menu.addAction(a)

        a_sleep = QAction("小憩打盹", self)
        a_sleep.triggered.connect(lambda: self.set_state("sleep", "稍微休息一下"))
        menu.addAction(a_sleep)

        menu.addSeparator()

        a_settings = QAction("设置（Kimi 连接 / 外观）", self)
        a_settings.triggered.connect(lambda: self.settings_triggered.emit())
        menu.addAction(a_settings)

        a_quit = QAction("退出", self)
        a_quit.triggered.connect(lambda: self.quit_triggered.emit())
        menu.addAction(a_quit)

        menu.exec(global_pos)
