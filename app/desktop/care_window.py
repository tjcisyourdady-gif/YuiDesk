"""独立桌宠养成浮窗（与 AI 对话窗口完全解耦，零 AI 依赖）."""

from __future__ import annotations

import ctypes
import os

from PySide6.QtCore import QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QCloseEvent
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget


class CareWindow(QWidget):
    CARD_WIDTH = 360
    CARD_HEIGHT = 480

    def __init__(self, base_url: str, always_on_top: bool = False) -> None:
        super().__init__(None)
        self._base_url = base_url.rstrip("/")
        self._always_on_top = bool(always_on_top)
        self._anchor_pet: QWidget | None = None
        self._page_ready = False

        self.setWindowTitle("YuiDesk 养成")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._apply_flags(show_again=False)
        self.resize(self.CARD_WIDTH, self.CARD_HEIGHT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._view = QWebEngineView(self)
        self._view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._view.setStyleSheet("background: transparent;")
        self._view.page().setBackgroundColor(QColor(0, 0, 0, 0))
        self._view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self._view.loadFinished.connect(lambda _ok: setattr(self, "_page_ready", True))
        self._view.setUrl(QUrl(self._base_url + "/care"))
        layout.addWidget(self._view)

    def _ensure_desktop_layer(self) -> None:
        if os.name != "nt" or self._always_on_top:
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

    def _apply_flags(self, show_again: bool = True) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags |= Qt.WindowType.WindowStaysOnBottomHint
        was_vis = self.isVisible()
        self.setWindowFlags(flags)
        if show_again and was_vis:
            self.show()
            if self._always_on_top:
                self.raise_()
            else:
                QTimer.singleShot(0, self._ensure_desktop_layer)

    def set_always_on_top(self, enabled: bool) -> None:
        clean = bool(enabled)
        if clean == self._always_on_top:
            return
        self._always_on_top = clean
        self._apply_flags(show_again=True)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._always_on_top:
            QTimer.singleShot(0, self._ensure_desktop_layer)

    def refresh(self) -> None:
        if self._page_ready:
            self._view.page().runJavaScript("window.refreshCare && window.refreshCare();")

    def _position_near_pet(self) -> None:
        if self._anchor_pet is None:
            return
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        pet_geo = self._anchor_pet.frameGeometry()

        w, h = self.CARD_WIDTH, self.CARD_HEIGHT
        # 优先停靠在桌宠左侧（方便一边点互动按钮，一边直接看桌宠表演动画！）
        if pet_geo.left() - avail.left() >= w + 12:
            tx = pet_geo.left() - w - 6
            ty = pet_geo.center().y() - h // 2
        elif avail.right() - pet_geo.right() >= w + 12:
            tx = pet_geo.right() + 6
            ty = pet_geo.center().y() - h // 2
        else:
            tx = pet_geo.center().x() - w // 2
            ty = pet_geo.bottom() + 4

        tx = max(avail.left() + 8, min(avail.right() - w - 8, tx))
        ty = max(avail.top() + 8, min(avail.bottom() - h - 8, ty))
        self.move(tx, ty)

    def show_near_pet(self, pet_widget: QWidget) -> None:
        self._anchor_pet = pet_widget
        self._position_near_pet()
        self.show()
        if self._always_on_top:
            self.raise_()
        else:
            QTimer.singleShot(0, self._ensure_desktop_layer)
        self.activateWindow()
        self.refresh()

    def toggle_near_pet(self, pet_widget: QWidget) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show_near_pet(pet_widget)

    def sync_to_pet(self, pet_widget: QWidget) -> None:
        self._anchor_pet = pet_widget
        if self.isVisible():
            self._position_near_pet()

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        event.ignore()
        self.hide()
