"""系统托盘常驻图标与极简菜单."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app.desktop.pet_renderer import AnimePetRenderer
from app.skins import get_skin


def create_app_icon() -> QIcon:
    skin = get_skin("default_sprite")
    idle_path = (skin.get("assets") or {}).get("idle")
    if idle_path and Path(idle_path).is_file():
        return QIcon(idle_path)
    pix = QPixmap(128, 128)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    AnimePetRenderer().draw(painter, QRectF(0, 0, 128, 128), state="happy", t=0.4)
    painter.end()
    return QIcon(pix)


class TrayManager:
    def __init__(
        self,
        parent,
        on_toggle_chat,
        on_screenshot,
        on_toggle_pet,
        on_open_settings,
        on_quit,
    ) -> None:
        self._tray = QSystemTrayIcon(create_app_icon(), parent)
        self._tray.setToolTip("YuiDesk (Alt+Space 唤醒对话)")

        menu = QMenu()
        a_chat = QAction("打开/收起对话 (Alt+Space)", menu)
        a_chat.triggered.connect(on_toggle_chat)
        menu.addAction(a_chat)

        a_shot = QAction("区域截屏提问 (Alt+S)", menu)
        a_shot.triggered.connect(on_screenshot)
        menu.addAction(a_shot)

        a_pet = QAction("显示/隐藏桌宠", menu)
        a_pet.triggered.connect(on_toggle_pet)
        menu.addAction(a_pet)

        menu.addSeparator()

        a_set = QAction("设置", menu)
        a_set.triggered.connect(on_open_settings)
        menu.addAction(a_set)

        a_quit = QAction("退出", menu)
        a_quit.triggered.connect(on_quit)
        menu.addAction(a_quit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_activated)
        self._on_toggle_chat = on_toggle_chat
        self._tray.show()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._on_toggle_chat()

    def hide(self) -> None:
        self._tray.hide()
