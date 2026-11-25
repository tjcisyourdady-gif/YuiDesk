"""60 FPS 多部位动画日漫轻音风 Q 版桌宠矢量渲染引擎（全 11 状态 + 待机彩蛋动作）."""

from __future__ import annotations

import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QLinearGradient,
)


class AnimePetRenderer:
    """绘制高精细、抗锯齿、60 FPS 骨骼联动动画的轻音元气 Q 版少女."""

    LOGICAL_SIZE = 200.0

    def draw(
        self,
        painter: QPainter,
        rect: QRectF,
        state: str,
        t: float,
        idle_submode: str = "normal",
        look_x: float = 0.0,
        look_y: float = 0.0,
        drag_vx: float = 0.0,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        scale = min(rect.width(), rect.height()) / self.LOGICAL_SIZE
        ox = rect.left() + (rect.width() - self.LOGICAL_SIZE * scale) / 2.0
        oy = rect.top() + (rect.height() - self.LOGICAL_SIZE * scale) / 2.0
        painter.translate(ox, oy)
        painter.scale(scale, scale)

        breath = math.sin(t * 2.6) * 1.8
        jump_y = 0.0
        body_tilt = 0.0
        shake_x = 0.0
        head_tilt = 0.0

        if state == "happy":
            hop = abs(math.sin(t * 6.5))
            jump_y = -hop * 16.0
            body_tilt = math.sin(t * 6.5) * 5.0
        elif state == "drag":
            body_tilt = max(-18.0, min(18.0, -drag_vx * 0.6 + math.sin(t * 9.0) * 8.0))
            jump_y = -6.0
        elif state == "thinking":
            head_tilt = 8.0 + math.sin(t * 1.8) * 2.5
        elif state == "searching":
            head_tilt = math.sin(t * 3.0) * 5.5
        elif state == "error":
            shake_x = math.sin(t * 36.0) * 2.6
            head_tilt = -5.0
        elif state == "sleep":
            breath = math.sin(t * 1.3) * 2.2
            head_tilt = 6.0 + math.sin(t * 1.3) * 5.0
            jump_y = 10.0
        elif state == "speaking":
            jump_y = -abs(math.sin(t * 5.2)) * 3.5
            body_tilt = math.sin(t * 4.2) * 3.0
        elif state == "hover":
            jump_y = -3.0 + math.sin(t * 4.0) * 2.0
            head_tilt = -4.0
        elif state == "file_catch":
            jump_y = -5.0 + math.sin(t * 6.0) * 2.5
        elif state == "idle" and idle_submode == "guitar":
            body_tilt = math.sin(t * 4.5) * 4.0
            jump_y = -abs(math.sin(t * 4.5)) * 2.5

        # 1. 脚底阴影 / 文件投喂光环
        self._draw_ground_effects(painter, state, t, jump_y)

        # 角色主体变换
        painter.save()
        painter.translate(100.0 + shake_x, 114.0 + jump_y + breath * 0.45)
        painter.rotate(body_tilt)
        painter.translate(-100.0, -114.0)

        # 2. 后层蓬松内扣栗色短发
        self._draw_back_hair(painter, state, t, head_tilt)

        # 3. 腿部与棕色乐福鞋
        self._draw_legs(painter, state, t)

        # 4. 轻音校服身体（海军蓝西装 + 百褶裙 + 珊瑚红蝴蝶结）
        self._draw_body(painter, state, t, breath)

        # 5. 非遮挡手臂（在头部之前绘制）
        self._draw_arms_back(painter, state, t, idle_submode)

        # 6. 头部（脸蛋、腮红、软萌大眼睛、小嘴、温柔弧线刘海、标志双黄发夹、呆毛）
        painter.save()
        painter.translate(100.0, 96.0)
        painter.rotate(head_tilt)
        painter.translate(-100.0, -96.0)
        self._draw_head(painter, state, t, look_x, look_y)
        painter.restore()

        # 7. 前景手势与道具（确保吉他、放大镜、书本、茶杯、招手小手清晰在最前层）
        self._draw_foreground_props(painter, state, t, idle_submode)

        painter.restore()

        # 8. 全矢量状态粒子特效（纯 QPainterPath 绘制，永不出现字体方框！）
        self._draw_state_particles(painter, state, t, idle_submode)

        painter.restore()

    def _draw_ground_effects(self, painter: QPainter, state: str, t: float, jump_y: float) -> None:
        if state == "file_catch":
            pulse = 1.0 + math.sin(t * 8.0) * 0.08
            glow = QRadialGradient(100, 178, 52 * pulse)
            glow.setColorAt(0.0, QColor(255, 196, 86, 150))
            glow.setColorAt(0.65, QColor(255, 122, 89, 85))
            glow.setColorAt(1.0, QColor(255, 122, 89, 0))
            painter.setBrush(QBrush(glow))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(100, 178), 52 * pulse, 16 * pulse)
            pen = QPen(QColor(255, 224, 130, 210), 2.0, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(100, 178), 42 * pulse, 11 * pulse)
            return

        if state == "drag":
            return

        shrink = max(0.55, 1.0 + jump_y * 0.022)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(45, 34, 30, 40))
        painter.drawEllipse(QPointF(100, 182), 34 * shrink, 8.5 * shrink)

    def _draw_back_hair(self, painter: QPainter, state: str, t: float, head_tilt: float) -> None:
        painter.save()
        painter.translate(100.0, 96.0)
        painter.rotate(head_tilt * 0.85)
        painter.translate(-100.0, -96.0)

        sway = math.sin(t * 2.4) * 2.0
        if state == "drag":
            sway = math.sin(t * 11.0) * 5.0

        # 柔和圆润的内扣 Bob 齐肩短发轮廓
        path = QPainterPath()
        path.moveTo(52, 74)
        path.cubicTo(44, 102, 47 + sway, 124, 65 + sway, 129)
        path.cubicTo(82, 133, 118, 133, 135 + sway, 129)
        path.cubicTo(153 + sway, 124, 156, 102, 148, 74)
        path.cubicTo(143, 39, 57, 39, 52, 74)
        path.closeSubpath()

        grad = QLinearGradient(100, 38, 100, 134)
        grad.setColorAt(0.0, QColor("#AC6E4A"))
        grad.setColorAt(0.55, QColor("#915938"))
        grad.setColorAt(1.0, QColor("#724227"))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor("#552F1A"), 2.1))
        painter.drawPath(path)
        painter.restore()

    def _draw_legs(self, painter: QPainter, state: str, t: float) -> None:
        if state == "sleep":
            painter.setPen(QPen(QColor("#4A2B18"), 2.0))
            painter.setBrush(QColor("#78482B"))
            painter.drawRoundedRect(QRectF(77, 162, 18, 11), 5, 5)
            painter.drawRoundedRect(QRectF(105, 162, 18, 11), 5, 5)
            return

        left_kick = 0.0
        right_kick = 0.0
        if state == "drag":
            left_kick = math.sin(t * 14.0) * 18.0
            right_kick = -math.sin(t * 14.0) * 18.0
        elif state == "happy":
            left_kick = -10.0
            right_kick = 10.0

        for cx, kick in [(88.0, left_kick), (112.0, right_kick)]:
            painter.save()
            painter.translate(cx, 150.0)
            painter.rotate(kick)
            painter.setPen(QPen(QColor("#6E4B3A"), 1.8))
            painter.setBrush(QColor("#FFE7D8"))
            painter.drawRoundedRect(QRectF(-5.5, 0, 11, 12), 4, 4)
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRoundedRect(QRectF(-5.5, 9, 11, 14), 3, 3)
            painter.setBrush(QColor("#73452A"))
            painter.setPen(QPen(QColor("#4A2B18"), 1.8))
            painter.drawRoundedRect(QRectF(-7.5, 20, 15, 9.5), 4.5, 4.5)
            painter.restore()

    def _draw_body(self, painter: QPainter, state: str, t: float, breath: float) -> None:
        skirt = QPainterPath()
        skirt.moveTo(81, 134)
        skirt.lineTo(119, 134)
        skirt.lineTo(131, 156)
        skirt.quadTo(100, 162, 69, 156)
        skirt.closeSubpath()
        skirt_grad = QLinearGradient(100, 134, 100, 160)
        skirt_grad.setColorAt(0.0, QColor("#5472A8"))
        skirt_grad.setColorAt(1.0, QColor("#3E5687"))
        painter.setBrush(QBrush(skirt_grad))
        painter.setPen(QPen(QColor("#28395C"), 2.0))
        painter.drawPath(skirt)

        painter.setPen(QPen(QColor("#2F436B"), 1.3))
        for px_top, px_bot in [(88, 82), (96, 94), (104, 106), (112, 118)]:
            painter.drawLine(QPointF(px_top, 137), QPointF(px_bot, 156))

        blazer = QPainterPath()
        blazer.moveTo(82, 106)
        blazer.lineTo(118, 106)
        blazer.cubicTo(123, 118, 123, 133, 120, 142)
        blazer.quadTo(100, 146, 80, 142)
        blazer.cubicTo(77, 133, 77, 118, 82, 106)
        blazer.closeSubpath()
        blazer_grad = QLinearGradient(100, 105, 100, 144)
        blazer_grad.setColorAt(0.0, QColor("#32456E"))
        blazer_grad.setColorAt(1.0, QColor("#233252"))
        painter.setBrush(QBrush(blazer_grad))
        painter.setPen(QPen(QColor("#1B2640"), 2.0))
        painter.drawPath(blazer)

        shirt = QPainterPath()
        shirt.moveTo(89, 105)
        shirt.lineTo(111, 105)
        shirt.lineTo(100, 124)
        shirt.closeSubpath()
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(QPen(QColor("#C8D2E3"), 1.2))
        painter.drawPath(shirt)

        painter.setBrush(QColor("#F7CA57"))
        painter.setPen(QPen(QColor("#B88924"), 1.0))
        painter.drawEllipse(QPointF(100, 129), 2.3, 2.3)
        painter.drawEllipse(QPointF(100, 136), 2.3, 2.3)

        ribbon_color = QColor("#FF5C6C")
        painter.setBrush(ribbon_color)
        painter.setPen(QPen(QColor("#A82C3C"), 1.5))
        left_bow = QPainterPath()
        left_bow.moveTo(100, 113)
        left_bow.lineTo(90, 108)
        left_bow.lineTo(91, 118)
        left_bow.closeSubpath()
        right_bow = QPainterPath()
        right_bow.moveTo(100, 113)
        right_bow.lineTo(110, 108)
        right_bow.lineTo(109, 118)
        right_bow.closeSubpath()
        painter.drawPath(left_bow)
        painter.drawPath(right_bow)
        painter.drawEllipse(QPointF(100, 113), 3.0, 2.6)

    def _draw_arm(self, painter: QPainter, shoulder: QPointF, angle_deg: float, length: float = 23.0) -> None:
        painter.save()
        painter.translate(shoulder)
        painter.rotate(angle_deg)
        painter.setBrush(QColor("#2C3E66"))
        painter.setPen(QPen(QColor("#1B2640"), 1.9))
        painter.drawRoundedRect(QRectF(-5.5, -2, 11, length), 5, 5)
        painter.setBrush(QColor("#FFE7D8"))
        painter.setPen(QPen(QColor("#78503D"), 1.6))
        painter.drawEllipse(QPointF(0, length + 1.5), 5.2, 4.8)
        painter.restore()

    def _draw_arms_back(self, painter: QPainter, state: str, t: float, idle_submode: str) -> None:
        left_sh = QPointF(80, 112)
        right_sh = QPointF(120, 112)

        if state == "hover":
            self._draw_arm(painter, left_sh, 24 + math.sin(t * 3.0) * 5)
        elif state == "happy":
            cheer = math.sin(t * 9.0) * 10
            self._draw_arm(painter, left_sh, 148 + cheer)
            self._draw_arm(painter, right_sh, -148 - cheer)
        elif state == "drag":
            flail = math.sin(t * 14.0) * 22
            self._draw_arm(painter, left_sh, 118 + flail)
            self._draw_arm(painter, right_sh, -118 + flail)
        elif state == "file_catch":
            self._draw_arm(painter, left_sh, 75 + math.sin(t * 6.0) * 6)
            self._draw_arm(painter, right_sh, -75 - math.sin(t * 6.0) * 6)
        elif state == "thinking":
            self._draw_arm(painter, left_sh, 18)
        elif state == "searching":
            self._draw_arm(painter, left_sh, 22)
        elif state in ("reading", "speaking") or (state == "idle" and idle_submode in ("guitar", "tea")):
            pass  # 这些状态手臂与道具一起画在前景层
        elif state == "error":
            self._draw_arm(painter, left_sh, 128 + math.sin(t * 20.0) * 5, length=20)
            self._draw_arm(painter, right_sh, -128 - math.sin(t * 20.0) * 5, length=20)
        elif state == "sleep":
            self._draw_arm(painter, left_sh, -18, length=19)
            self._draw_arm(painter, right_sh, 18, length=19)
        else:
            sway = math.sin(t * 2.4) * 5.0
            self._draw_arm(painter, left_sh, 22 + sway)
            self._draw_arm(painter, right_sh, -22 - sway)

    def _draw_foreground_props(self, painter: QPainter, state: str, t: float, idle_submode: str) -> None:
        left_sh = QPointF(80, 112)
        right_sh = QPointF(120, 112)

        if state == "hover":
            # 招手右手画在前景，清晰活泼
            wave = -126 + math.sin(t * 10.0) * 16
            self._draw_arm(painter, QPointF(122, 114), wave, length=22)
        elif state == "thinking":
            # 托腮小手放在下巴前
            painter.save()
            painter.setBrush(QColor("#FFE7D8"))
            painter.setPen(QPen(QColor("#78503D"), 1.6))
            painter.drawEllipse(QPointF(114, 108), 5.6, 5.0)
            painter.restore()
        elif state == "searching":
            sweep = -92 + math.sin(t * 4.2) * 14
            self._draw_arm(painter, QPointF(121, 114), sweep, length=22)
            self._draw_magnifying_glass(painter, t)
        elif state == "reading":
            self._draw_arm(painter, left_sh, -25, length=20)
            self._draw_arm(painter, right_sh, 25, length=20)
            self._draw_open_book(painter, t)
        elif state == "speaking" or (state == "idle" and idle_submode == "guitar"):
            self._draw_mini_guitar(painter, t)
            self._draw_arm(painter, left_sh, -28, length=20)
            strum = 32 + math.sin(t * 13.0) * 14
            self._draw_arm(painter, right_sh, strum, length=20)
        elif state == "idle" and idle_submode == "tea":
            self._draw_arm(painter, left_sh, -18, length=20)
            self._draw_arm(painter, right_sh, 18, length=20)
            self._draw_teacup(painter, t)

    def _draw_mini_guitar(self, painter: QPainter, t: float) -> None:
        painter.save()
        painter.translate(102, 134)
        painter.rotate(-22 + math.sin(t * 5.0) * 3.0)

        painter.setPen(QPen(QColor("#4A2B16"), 1.6))
        painter.setBrush(QColor("#D7A46B"))
        painter.drawRoundedRect(QRectF(-34, -3.5, 36, 7), 2, 2)
        painter.setBrush(QColor("#3E2723"))
        painter.drawRoundedRect(QRectF(-44, -5.5, 12, 11), 3, 3)

        body = QPainterPath()
        body.addEllipse(QPointF(10, 0), 17, 13.5)
        body.addEllipse(QPointF(-3, 0), 11, 9.5)
        grad = QRadialGradient(8, -2, 20)
        grad.setColorAt(0.0, QColor("#FFD166"))
        grad.setColorAt(0.55, QColor("#F0713E"))
        grad.setColorAt(1.0, QColor("#A62C2B"))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor("#5C1919"), 1.8))
        painter.drawPath(body)

        painter.setBrush(QColor("#FFF3DC"))
        painter.setPen(QPen(QColor("#C8A878"), 1.0))
        painter.drawEllipse(QPointF(8, 3), 8, 5.5)
        painter.setBrush(QColor("#E5E7EB"))
        painter.drawRect(QRectF(0, -4.5, 5, 9))
        painter.drawRect(QRectF(10, -4.5, 5, 9))
        painter.restore()

    def _draw_magnifying_glass(self, painter: QPainter, t: float) -> None:
        painter.save()
        dx = math.sin(t * 4.2) * 7.0
        dy = math.cos(t * 4.2) * 3.0
        painter.translate(148 + dx, 102 + dy)
        painter.rotate(-22 + math.sin(t * 4.2) * 10)
        painter.setPen(QPen(QColor("#6E411C"), 4.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(0, 12), QPointF(0, 27))
        painter.setPen(QPen(QColor("#F4B942"), 3.2))
        painter.setBrush(QColor(173, 232, 255, 150))
        painter.drawEllipse(QPointF(0, 0), 13.5, 13.5)
        painter.setPen(QPen(QColor(255, 255, 255, 220), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(QRectF(-8, -8, 16, 16), 110 * 16, 55 * 16)
        painter.restore()

    def _draw_open_book(self, painter: QPainter, t: float) -> None:
        painter.save()
        painter.translate(100, 138 + math.sin(t * 3.0) * 1.5)
        painter.setPen(QPen(QColor("#5C4B3B"), 1.6))
        painter.setBrush(QColor("#FFFDF7"))
        left = QPainterPath()
        left.moveTo(0, -8)
        left.quadTo(-13, -12, -24, -6)
        left.lineTo(-22, 12)
        left.quadTo(-11, 8, 0, 12)
        left.closeSubpath()
        painter.drawPath(left)
        right = QPainterPath()
        right.moveTo(0, -8)
        right.quadTo(13, -12, 24, -6)
        right.lineTo(22, 12)
        right.quadTo(11, 8, 0, 12)
        right.closeSubpath()
        painter.drawPath(right)
        painter.setPen(QPen(QColor("#B8A99A"), 1.2))
        for y in (-3, 1, 5):
            painter.drawLine(QPointF(-18, y), QPointF(-5, y))
            painter.drawLine(QPointF(5, y), QPointF(18, y))
        painter.restore()

    def _draw_teacup(self, painter: QPainter, t: float) -> None:
        painter.save()
        painter.translate(100, 138)
        painter.setBrush(QColor("#FFF8F0"))
        painter.setPen(QPen(QColor("#D98E73"), 1.8))
        painter.drawRoundedRect(QRectF(-10, -4, 20, 14), 5, 5)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(6, -1, 8, 8), -90 * 16, 180 * 16)
        # 温暖红茶热气
        alpha = int(140 + math.sin(t * 3.5) * 70)
        painter.setPen(QPen(QColor(255, 196, 150, alpha), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for sx in (-4, 4):
            wobble = math.sin(t * 4.0 + sx) * 2.0
            painter.drawLine(QPointF(sx, -8), QPointF(sx + wobble, -18))
        painter.restore()

    def _draw_head(
        self,
        painter: QPainter,
        state: str,
        t: float,
        look_x: float,
        look_y: float,
    ) -> None:
        painter.setBrush(QColor("#FFE5D4"))
        painter.setPen(QPen(QColor("#825641"), 1.6))
        painter.drawEllipse(QPointF(58, 86), 5.5, 7.0)
        painter.drawEllipse(QPointF(142, 86), 5.5, 7.0)

        face_grad = QRadialGradient(100, 76, 44)
        face_grad.setColorAt(0.0, QColor("#FFF3EB"))
        face_grad.setColorAt(0.85, QColor("#FFE4D1"))
        face_grad.setColorAt(1.0, QColor("#F8D0B8"))
        painter.setBrush(QBrush(face_grad))
        painter.setPen(QPen(QColor("#784E3B"), 2.0))
        face = QPainterPath()
        face.moveTo(60, 72)
        face.cubicTo(59, 98, 72, 111, 100, 112)
        face.cubicTo(128, 111, 141, 98, 140, 72)
        face.cubicTo(140, 46, 60, 46, 60, 72)
        face.closeSubpath()
        painter.drawPath(face)

        # 暖粉软萌腮红 + 日漫斜线高光
        blush_alpha = 165 if state in ("hover", "happy", "file_catch") else 115
        for bx in (72.5, 127.5):
            blush = QRadialGradient(bx, 94.5, 10.5)
            blush.setColorAt(0.0, QColor(255, 130, 152, blush_alpha))
            blush.setColorAt(1.0, QColor(255, 130, 152, 0))
            painter.setBrush(QBrush(blush))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(bx, 94.5), 10.5, 6.0)
            painter.setPen(QPen(QColor(255, 115, 138, 140), 1.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(bx - 3, 96), QPointF(bx - 1, 93))
            painter.drawLine(QPointF(bx + 1, 96), QPointF(bx + 3, 93))

        # 眼睛
        self._draw_eyes(painter, state, t, look_x, look_y)

        # 阅读小圆框眼镜
        if state == "reading":
            painter.setPen(QPen(QColor("#D98C36"), 2.0))
            painter.setBrush(QColor(255, 255, 255, 45))
            painter.drawEllipse(QPointF(81.5, 85), 12.2, 10.2)
            painter.drawEllipse(QPointF(118.5, 85), 12.2, 10.2)
            painter.drawLine(QPointF(93.7, 85), QPointF(106.3, 85))

        # 嘴巴
        self._draw_mouth(painter, state, t)

        # 温柔蓬松栗色刘海 + 双黄色发夹 + 呆毛
        self._draw_front_hair_and_pins(painter, state, t)

    def _draw_eyes(
        self,
        painter: QPainter,
        state: str,
        t: float,
        look_x: float,
        look_y: float,
    ) -> None:
        if state == "sleep":
            pen = QPen(QColor("#4A2B18"), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(QRectF(72, 82, 18, 10), 195 * 16, 150 * 16)
            painter.drawArc(QRectF(110, 82, 18, 10), 195 * 16, 150 * 16)
            return

        if state == "happy":
            pen = QPen(QColor("#4A2B18"), 2.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(QRectF(72, 80, 18, 13), 15 * 16, 150 * 16)
            painter.drawArc(QRectF(110, 80, 18, 13), 15 * 16, 150 * 16)
            return

        if state == "error":
            pen = QPen(QColor("#4A2B18"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(75, 80), QPointF(87, 85))
            painter.drawLine(QPointF(87, 85), QPointF(75, 90))
            painter.drawLine(QPointF(125, 80), QPointF(113, 85))
            painter.drawLine(QPointF(113, 85), QPointF(125, 90))
            return

        blink_cycle = t % 3.4
        if state in ("idle", "speaking", "reading") and blink_cycle > 3.26:
            pen = QPen(QColor("#4A2B18"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(73, 86), QPointF(90, 86))
            painter.drawLine(QPointF(110, 86), QPointF(127, 86))
            return

        px = max(-2.5, min(2.5, look_x * 2.4))
        py = max(-2.0, min(2.0, look_y * 1.8))
        if state == "thinking":
            px, py = 2.4, -2.2
        elif state == "reading":
            px, py = math.sin(t * 5.0) * 2.4, 1.8
        elif state == "searching":
            px, py = math.sin(t * 4.2) * 2.6, -0.5

        star_eyes = state in ("hover", "file_catch")

        for ex in (81.5, 118.5):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(QPointF(ex, 85.5), 9.6, 10.2)

            iris_grad = QLinearGradient(ex, 76, ex, 96)
            iris_grad.setColorAt(0.0, QColor("#5B321B"))
            iris_grad.setColorAt(0.55, QColor("#A35E2E"))
            iris_grad.setColorAt(1.0, QColor("#E8A452"))
            painter.setBrush(QBrush(iris_grad))
            painter.drawEllipse(QPointF(ex + px, 86.0 + py), 7.6, 8.6)

            painter.setBrush(QColor("#3A1E0E"))
            painter.drawEllipse(QPointF(ex + px, 86.3 + py), 3.8, 4.4)

            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(QPointF(ex + px - 2.6, 82.2 + py), 2.6, 2.6)
            painter.drawEllipse(QPointF(ex + px + 2.4, 89.0 + py), 1.4, 1.4)

            if star_eyes:
                painter.setBrush(QColor("#FFF3B0"))
                self._draw_tiny_star(painter, QPointF(ex + px + 1.6, 83.0 + py), 2.7)

            # 温柔微弯上睫毛
            lash = QPainterPath()
            lash.moveTo(ex - 10.0, 82.8)
            lash.quadTo(ex, 73.2, ex + 10.0, 82.8)
            painter.setPen(QPen(QColor("#422313"), 2.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(lash)

    def _draw_mouth(self, painter: QPainter, state: str, t: float) -> None:
        pen = QPen(QColor("#8C4A3B"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        if state == "drag":
            painter.setBrush(QColor("#F48B94"))
            painter.drawEllipse(QPointF(100, 101.0), 3.6, 4.4)
        elif state == "error":
            p = QPainterPath()
            p.moveTo(93.5, 101.5)
            p.cubicTo(96, 98.5, 98, 104.0, 100, 101.0)
            p.cubicTo(102, 98.5, 104, 104.0, 106.5, 101.5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(p)
        elif state == "thinking":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(QRectF(96, 99.0, 8, 5), 20 * 16, 140 * 16)
        elif state == "sleep":
            painter.setBrush(QColor("#F29DA5"))
            painter.drawEllipse(QPointF(100, 101.0), 2.4, 2.8)
            r = 4.5 + math.sin(t * 2.2) * 2.2
            painter.setPen(QPen(QColor(180, 225, 255, 210), 1.4))
            painter.setBrush(QColor(215, 242, 255, 130))
            painter.drawEllipse(QPointF(105.5, 99.0), r, r)
        elif state == "speaking":
            open_h = 2.0 + abs(math.sin(t * 14.0)) * 4.5
            painter.setBrush(QColor("#F27988"))
            painter.drawEllipse(QPointF(100, 100.5), 4.6, open_h)
        elif state in ("happy", "hover", "file_catch"):
            mouth = QPainterPath()
            mouth.moveTo(93.5, 98.0)
            mouth.lineTo(106.5, 98.0)
            mouth.quadTo(100, 107.8, 93.5, 98.0)
            painter.setBrush(QColor("#F27988"))
            painter.drawPath(mouth)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(QRectF(95, 96.0, 10, 7.5), 205 * 16, 130 * 16)

    def _draw_front_hair_and_pins(self, painter: QPainter, state: str, t: float) -> None:
        # 柔和圆弧分叉刘海（位于眉眼上方，展现软萌甜美气质）
        hair = QPainterPath()
        hair.moveTo(54, 78)
        hair.cubicTo(52, 42, 74, 31, 100, 31)
        hair.cubicTo(126, 31, 148, 42, 146, 78)
        # 右侧微卷鬓角
        hair.cubicTo(148, 96, 144, 114, 136, 119)
        hair.cubicTo(136, 100, 139, 82, 135, 66)
        # 温柔日漫曲线刘海
        hair.quadTo(129, 73, 123, 64)
        hair.quadTo(116, 73, 108, 63)
        hair.quadTo(100, 74, 92, 63)
        hair.quadTo(84, 73, 77, 64)
        hair.quadTo(71, 73, 65, 66)
        # 左侧微卷鬓角
        hair.cubicTo(61, 82, 64, 100, 64, 119)
        hair.cubicTo(56, 114, 52, 96, 54, 78)
        hair.closeSubpath()

        grad = QLinearGradient(100, 30, 100, 114)
        grad.setColorAt(0.0, QColor("#BE7E55"))
        grad.setColorAt(0.45, QColor("#A0633F"))
        grad.setColorAt(1.0, QColor("#814C2E"))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor("#552F1A"), 2.1))
        painter.drawPath(hair)

        # 天使光环发丝高光
        shine = QPainterPath()
        shine.moveTo(70, 51)
        shine.quadTo(100, 43, 130, 51)
        painter.setPen(QPen(QColor(255, 228, 198, 155), 3.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(shine)

        # 标志性双黄色小发夹
        painter.save()
        painter.translate(125, 59)
        painter.rotate(24)
        painter.setBrush(QColor("#FFD644"))
        painter.setPen(QPen(QColor("#B58110"), 1.3))
        painter.drawRoundedRect(QRectF(-8, -3.5, 16, 3.8), 1.8, 1.8)
        painter.drawRoundedRect(QRectF(-7, 1.8, 16, 3.8), 1.8, 1.8)
        painter.restore()

        # 灵动呆毛
        ahoge_wobble = math.sin(t * (10.0 if state == "happy" else 3.2)) * (9.0 if state == "happy" else 3.5)
        ahoge_droop = 10.0 if state in ("sleep", "error") else 0.0
        ahoge = QPainterPath()
        ahoge.moveTo(98, 32)
        ahoge.cubicTo(94, 15 + ahoge_droop, 108 + ahoge_wobble, 11 + ahoge_droop, 113 + ahoge_wobble, 22 + ahoge_droop)
        painter.setPen(QPen(QColor("#552F1A"), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(ahoge)
        painter.setPen(QPen(QColor("#BE7E55"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(ahoge)

    def _draw_vector_note(self, painter: QPainter, x: float, y: float, color: QColor, double: bool = False) -> None:
        """纯矢量绘制可爱音符（不依赖系统字体，永不乱码）."""
        painter.save()
        painter.translate(x, y)
        painter.setBrush(color)
        painter.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if not double:
            painter.drawEllipse(QPointF(0, 0), 3.6, 2.7)
            painter.drawLine(QPointF(3.2, 0), QPointF(3.2, -11.5))
            flag = QPainterPath()
            flag.moveTo(3.2, -11.5)
            flag.quadTo(9.0, -9.5, 8.2, -4.5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(flag)
        else:
            painter.drawEllipse(QPointF(-4, 1), 3.2, 2.4)
            painter.drawEllipse(QPointF(5, -1), 3.2, 2.4)
            painter.drawLine(QPointF(-1, 1), QPointF(-1, -10.5))
            painter.drawLine(QPointF(8, -1), QPointF(8, -12.5))
            painter.setPen(QPen(color, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(-1, -10.5), QPointF(8, -12.5))
        painter.restore()

    def _draw_vector_z(self, painter: QPainter, x: float, y: float, size: float, color: QColor) -> None:
        """纯矢量绘制睡眠 Z 字符."""
        painter.save()
        painter.translate(x, y)
        painter.setPen(QPen(color, 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        p = QPainterPath()
        p.moveTo(0, 0)
        p.lineTo(size, 0)
        p.lineTo(0, size * 1.15)
        p.lineTo(size, size * 1.15)
        painter.drawPath(p)
        painter.restore()

    def _draw_state_particles(
        self,
        painter: QPainter,
        state: str,
        t: float,
        idle_submode: str,
    ) -> None:
        if state == "thinking":
            glow_a = int(120 + math.sin(t * 6.0) * 65)
            glow = QRadialGradient(148, 36, 19)
            glow.setColorAt(0.0, QColor(255, 225, 95, glow_a))
            glow.setColorAt(1.0, QColor(255, 225, 95, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(QPointF(148, 36), 19, 19)

            painter.setBrush(QColor("#FFE169"))
            painter.setPen(QPen(QColor("#B77E14"), 1.6))
            painter.drawEllipse(QPointF(148, 34), 8.5, 9.5)
            painter.setBrush(QColor("#94A3B8"))
            painter.drawRoundedRect(QRectF(144, 42, 8, 4.5), 1.5, 1.5)
            for i, (dx, dy) in enumerate([(132, 54), (138, 48)]):
                a = int(150 + math.sin(t * 5.0 - i) * 80)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 240, 200, a))
                painter.drawEllipse(QPointF(dx, dy), 2.5 + i * 0.8, 2.5 + i * 0.8)

        elif state == "searching":
            for i in range(2):
                prog = (t * 0.8 + i * 0.5) % 1.0
                r = 10.0 + prog * 22.0
                alpha = int((1.0 - prog) * 190)
                painter.setPen(QPen(QColor(56, 189, 248, alpha), 2.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(152, 42), r, r)
            painter.setBrush(QColor("#38BDF8"))
            painter.setPen(QPen(QColor("#0284C7"), 1.5))
            painter.drawEllipse(QPointF(152, 42), 8.0, 8.0)

        elif state == "speaking" or (state == "idle" and idle_submode == "guitar"):
            notes = [(False, 42, "#FF6B8B", 0.0), (True, 158, "#FF9F43", 0.55), (False, 144, "#54A0FF", 1.1)]
            for dbl, bx, col, phase in notes:
                prog = (t * 0.72 + phase) % 1.5
                y = 68 - prog * 34
                x = bx + math.sin(t * 3.5 + phase) * 5
                alpha = int(max(0, min(255, (1.5 - prog) * 210)))
                c = QColor(col)
                c.setAlpha(alpha)
                self._draw_vector_note(painter, x, y, c, double=dbl)

        elif state == "happy":
            for i in range(5):
                angle = t * 2.2 + i * (math.tau / 5)
                sx = 100 + math.cos(angle) * 64
                sy = 78 + math.sin(angle) * 44 - 10
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#FFD447" if i % 2 == 0 else "#FF6B8B"))
                self._draw_tiny_star(painter, QPointF(sx, sy), 5.5 + math.sin(t * 8 + i) * 1.5)

        elif state == "error":
            drop_y = 58 + ((t * 24) % 16)
            drop = QPainterPath()
            drop.moveTo(138, drop_y - 7)
            drop.cubicTo(143, drop_y + 1, 143, drop_y + 7, 138, drop_y + 7)
            drop.cubicTo(133, drop_y + 7, 133, drop_y + 1, 138, drop_y - 7)
            painter.setBrush(QColor("#60A5FA"))
            painter.setPen(QPen(QColor("#2563EB"), 1.3))
            painter.drawPath(drop)

        elif state == "sleep":
            for i, sz in enumerate([7.0, 9.0, 11.0]):
                prog = (t * 0.42 + i * 0.33) % 1.0
                x = 132 + i * 11 + math.sin(t * 2.0 + i) * 3
                y = 62 - prog * 36
                alpha = int(math.sin(prog * math.pi) * 235)
                self._draw_vector_z(painter, x, y, sz, QColor(129, 140, 248, max(0, alpha)))

        elif state == "idle":
            prog = (t * 0.32) % 2.4
            if prog < 1.2:
                alpha = int(math.sin((prog / 1.2) * math.pi) * 195)
                c = QColor(255, 122, 89, max(0, alpha))
                self._draw_vector_note(painter, 148 + math.sin(t * 2.5) * 4, 56 - prog * 18, c, double=False)

    def _draw_tiny_star(self, painter: QPainter, center: QPointF, radius: float) -> None:
        path = QPainterPath()
        for i in range(8):
            r = radius if i % 2 == 0 else radius * 0.38
            ang = i * (math.pi / 4.0) - math.pi / 2.0
            pt = QPointF(center.x() + math.cos(ang) * r, center.y() + math.sin(ang) * r)
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        path.closeSubpath()
        painter.drawPath(path)
