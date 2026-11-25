"""Windows 全屏区域截屏遮罩（框选后保存 PNG 并发送给对话窗口）."""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class ScreenshotOverlay(QWidget):
    captured = Signal(bytes)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._full_pixmap: QPixmap | None = None
        self._origin = QPoint()
        self._current = QPoint()
        self._dragging = False

    def start_capture(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if not screen:
            self.cancelled.emit()
            return
        geo = screen.geometry()
        self._full_pixmap = screen.grabWindow(0)
        self.setGeometry(geo)
        self._origin = QPoint()
        self._current = QPoint()
        self._dragging = False
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def _selection_rect(self) -> QRect:
        return QRect(self._origin, self._current).normalized()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        if not self._full_pixmap:
            return
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._full_pixmap)
        # 半透明暗幕
        painter.fillRect(self.rect(), QColor(15, 18, 28, 125))

        rect = self._selection_rect()
        if self._dragging and rect.width() > 4 and rect.height() > 4:
            dpr = self._full_pixmap.devicePixelRatio()
            src = QRect(
                int(rect.x() * dpr),
                int(rect.y() * dpr),
                int(rect.width() * dpr),
                int(rect.height() * dpr),
            )
            painter.drawPixmap(rect, self._full_pixmap, src)
            pen = QPen(QColor("#FF7A59"), 2)
            painter.setPen(pen)
            painter.drawRect(rect)
            # 尺寸提示角标
            label = f"{rect.width()} × {rect.height()}  (松手发送给桌宠 · ESC取消)"
            painter.setPen(QColor("#FFFFFF"))
            tip_y = rect.top() - 8 if rect.top() > 28 else rect.bottom() + 20
            painter.drawText(rect.left() + 4, tip_y, label)
        else:
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "按住鼠标左键框选屏幕区域，松手发给 AI 助手识图  ·  按 ESC 或右键取消",
            )

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self._dragging = True
            self.update()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._dragging:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            rect = self._selection_rect()
            self.hide()
            if self._full_pixmap and rect.width() > 8 and rect.height() > 8:
                dpr = self._full_pixmap.devicePixelRatio()
                src = QRect(
                    int(rect.x() * dpr),
                    int(rect.y() * dpr),
                    int(rect.width() * dpr),
                    int(rect.height() * dpr),
                )
                cropped = self._full_pixmap.copy(src)
                buf = QBuffer()
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                cropped.save(buf, "PNG")
                self.captured.emit(bytes(buf.data()))
            else:
                self.cancelled.emit()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()

    def _cancel(self) -> None:
        self._dragging = False
        self.hide()
        self.cancelled.emit()
