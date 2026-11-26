"""桌宠正下方无边框圆角悬浮对话框 + 独立设置窗口."""

from __future__ import annotations

import ctypes
import json
import os
from typing import Any

from PySide6.QtCore import QRect, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCloseEvent
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget


class _ExternalLinkPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # type: ignore[override]
        if (
            nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
            and url.host() not in ("127.0.0.1", "localhost")
        ):
            # 仅允许安全打开 http/https 外链，防止恶意文本触发 file:// 或系统协议
            if url.scheme() in ("http", "https"):
                from PySide6.QtGui import QDesktopServices

                QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class ChatWindow(QWidget):
    dialog_hidden = Signal()

    DIALOG_WIDTH = 360
    SIDEBAR_DIALOG_WIDTH = 496
    COMPACT_HEIGHT = 132
    MAX_DIALOG_HEIGHT = 720

    def __init__(self, base_url: str, always_on_top: bool = False) -> None:
        super().__init__(None)
        self._base_url = base_url.rstrip("/")
        self._always_on_top = bool(always_on_top)
        self._mode = "dialog"  # dialog | settings
        self._dialog_width = self.SIDEBAR_DIALOG_WIDTH
        self._dialog_height = 330
        self._anchor_pet: QWidget | None = None
        self._page_ready = False
        self._pending_js: list[str] = []

        self.setWindowTitle("YuiDesk")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._view = QWebEngineView(self)
        self._view.setPage(_ExternalLinkPage(self._view))
        self._view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._view.setStyleSheet("background: transparent;")
        self._view.page().setBackgroundColor(QColor(0, 0, 0, 0))

        s = self._view.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)

        self._view.loadFinished.connect(self._on_load_finished)
        self._view.setUrl(QUrl(self._base_url + "/"))
        layout.addWidget(self._view)

    def _on_load_finished(self, ok: bool) -> None:
        self._page_ready = True
        for script in self._pending_js:
            self._view.page().runJavaScript(script)
        self._pending_js.clear()

    def dispatch_event(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        data_json = json.dumps(payload or {}, ensure_ascii=False)
        js = f"window.onDesktopEvent && window.onDesktopEvent({json.dumps(event_name)}, {data_json});"
        if self._page_ready:
            self._view.page().runJavaScript(js)
        else:
            self._pending_js.append(js)

    def _position_under_pet(self) -> None:
        if self._mode != "dialog" or self._anchor_pet is None:
            return
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        pet_geo = self._anchor_pet.frameGeometry()

        w = self._dialog_width
        h = self._dialog_height
        self.resize(w, h)

        # 若桌宠下方空间不足，向上微移桌宠确保对话框紧贴在桌宠正下方
        if avail.bottom() - pet_geo.bottom() < h + 10:
            new_pet_y = max(avail.top() + 8, avail.bottom() - h - pet_geo.height() - 10)
            self._anchor_pet.move(pet_geo.x(), new_pet_y)
            pet_geo = self._anchor_pet.frameGeometry()

        tx = pet_geo.center().x() - w // 2
        ty = pet_geo.bottom() + 2
        tx = max(avail.left() + 8, min(avail.right() - w - 8, tx))
        ty = max(avail.top() + 8, min(avail.bottom() - h - 8, ty))
        self.move(tx, ty)

    def sync_to_pet(self, pet_widget: QWidget) -> None:
        """桌宠被拖动时，如果对话框正打开着，实时跟随停在桌宠正下方."""
        self._anchor_pet = pet_widget
        if self.isVisible() and self._mode == "dialog":
            self._position_under_pet()

    def set_dialog_height(self, height: int) -> None:
        self.set_dialog_size(self._dialog_width, height)

    def set_dialog_size(self, width: int, height: int) -> None:
        clamped_w = max(320, min(800, int(width)))
        clamped_h = max(self.COMPACT_HEIGHT, min(self.MAX_DIALOG_HEIGHT, int(height)))
        if clamped_w == self._dialog_width and clamped_h == self._dialog_height:
            return
        self._dialog_width = clamped_w
        self._dialog_height = clamped_h
        if self._mode == "dialog" and self.isVisible():
            self._position_under_pet()

    def _dialog_window_flags(self) -> Qt.WindowType:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            # 与桌宠保持同一桌面层等级，不浮在其他应用窗口之上
            flags |= Qt.WindowType.WindowStaysOnBottomHint
        return flags

    def _ensure_desktop_layer(self) -> None:
        if os.name != "nt" or self._always_on_top or self._mode != "dialog":
            return
        try:
            hwnd = int(self.winId())
            if hwnd:
                HWND_BOTTOM = 1
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_NOACTIVATE = 0x0010
                ctypes.windll.user32.SetWindowPos(
                    hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                )
        except Exception:
            pass

    def set_always_on_top(self, enabled: bool) -> None:
        clean = bool(enabled)
        if clean == self._always_on_top:
            return
        self._always_on_top = clean
        if self._mode == "dialog":
            was_vis = self.isVisible()
            self.setWindowFlags(self._dialog_window_flags())
            self._view.page().setBackgroundColor(QColor(0, 0, 0, 0))
            if was_vis:
                self.show()
                if clean:
                    self.raise_()
                else:
                    QTimer.singleShot(0, self._ensure_desktop_layer)

    def show_under_pet(self, pet_widget: QWidget) -> None:
        """在桌宠正下方弹出无边框紧凑圆角输入卡片."""
        self._anchor_pet = pet_widget
        switching = self._mode != "dialog"
        self._mode = "dialog"
        desired_flags = self._dialog_window_flags()
        if switching or self.windowFlags() != desired_flags:
            self.setWindowFlags(desired_flags)
            self._view.page().setBackgroundColor(QColor(0, 0, 0, 0))

        self._position_under_pet()
        self.show()
        if self._always_on_top:
            self.raise_()
        else:
            QTimer.singleShot(0, self._ensure_desktop_layer)
        self.activateWindow()
        self.dispatch_event("open_dialog", {})

    def show_settings(self, tab: str = "providers") -> None:
        """仅右键桌宠点「设置」时打开的独立设置窗口."""
        self._mode = "settings"
        self.setWindowTitle("YuiDesk 设置")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint)
        self._view.page().setBackgroundColor(QColor("#FAF9F7"))
        w, h = 760, 560
        self.resize(w, h)
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            self.move(avail.center().x() - w // 2, avail.center().y() - h // 2)
        self.show()
        self.raise_()
        self.activateWindow()
        self.dispatch_event("open_settings", {"tab": tab})

    def hide_dialog(self) -> None:
        was_vis = self.isVisible()
        self.hide()
        if was_vis:
            self.dialog_hidden.emit()

    def toggle_under_pet(self, pet_widget: QWidget) -> None:
        if self.isVisible() and self._mode == "dialog":
            self.hide_dialog()
        else:
            self.show_under_pet(pet_widget)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._always_on_top and self._mode == "dialog":
            QTimer.singleShot(0, self._ensure_desktop_layer)

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        event.ignore()
        self.hide_dialog()
