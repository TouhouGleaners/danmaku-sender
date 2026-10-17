"""字段输入框的边框与步进区。

圆角填充、细框、底部灰线，聚焦时底部灰线换为强调色。
底部灰线不沿周长描边，而是两端各内缩一个圆角半径的圆头短线。
取值居中，左右为步进区，悬停或聚焦时复现加减号。
笔画与外框按设备像素对齐，高 DPI 下边缘不发虚。
"""

import math
from typing import NamedTuple

from PySide6.QtCore import QEvent, QLineF, QObject, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QDoubleSpinBox,
    QLineEdit,
    QSpinBox,
    QWidget,
)


class _Stroke(NamedTuple):
    """对齐到设备像素后的描边矩形与笔宽。"""

    rect: QRectF
    width: float


class _PaintMetrics:
    """将矩形与笔画对齐到设备像素。

    以画笔的 ``deviceTransform`` 为准，它同时覆盖高 DPI 缩放、重定向绘制与小数位移。

    Typical usage example::

        metrics = _PaintMetrics(painter)
        stroke = metrics.aligned_stroke(widget.rect(), 1.0)
    """

    def __init__(self, painter: QPainter) -> None:
        """读取画笔的设备变换并判定是否可压齐。

        Args:
            painter (QPainter): 正在绘制的画笔。
        """
        self._transform = painter.deviceTransform()
        self._scale_x = abs(self._transform.m11())
        self._scale_y = abs(self._transform.m22())
        self._axis_aligned = (
            abs(self._transform.m12()) < 1e-6
            and abs(self._transform.m21()) < 1e-6
            and self._transform.m11() != 0
            and self._transform.m22() != 0
            and self._transform.isInvertible()
        )

    @staticmethod
    def _qround(value: float) -> int:
        """按 Qt 的 qRound 取整，半数远离零。

        Args:
            value (float): 待取整的数值。

        Returns:
            int: 取整结果。
        """
        return int(value + 0.5) if value >= 0 else int(value - 0.5)

    def aligned_outer_rect(self, rect: QRectF) -> QRectF:
        """把逻辑矩形的四边压到设备像素。

        Args:
            rect (QRectF): 逻辑坐标下的矩形。

        Returns:
            QRectF: 压齐后的逻辑矩形。
        """
        if not self._axis_aligned or not rect.isValid() or rect.isEmpty():
            return rect
        device = self._transform.mapRect(rect).normalized()
        left = self._qround(device.left())
        top = self._qround(device.top())
        right = max(left, self._qround(device.right()))
        bottom = max(top, self._qround(device.bottom()))
        snapped = QRectF(left, top, right - left, bottom - top)
        inverted, ok = self._transform.inverted()
        return inverted.mapRect(snapped).normalized() if ok else rect

    def aligned_stroke(self, rect: QRectF, width: float) -> _Stroke:
        """返回对齐到设备像素的描边矩形与笔宽。

        Args:
            rect (QRectF): 逻辑坐标下的外框矩形。
            width (float): 逻辑笔宽。

        Returns:
            _Stroke: 对齐后的描边矩形与笔宽；笔宽非正时笔宽为 0。
        """
        if width <= 0 or not rect.isValid() or rect.isEmpty():
            return _Stroke(rect, 0.0)
        inset = width / 2
        fallback = rect.adjusted(inset, inset, -inset, -inset)
        if not self._axis_aligned or not math.isclose(self._scale_x, self._scale_y):
            return _Stroke(fallback, width)

        device = self._transform.mapRect(self.aligned_outer_rect(rect)).normalized()
        physical = max(1, self._qround(width * self._scale_x))
        inset = physical / 2
        device.adjust(inset, inset, -inset, -inset)
        inverted, ok = self._transform.inverted()
        aligned = inverted.mapRect(device).normalized() if ok else fallback
        return _Stroke(aligned, physical / self._scale_x)


class _FieldChrome:
    """字段边框与步进区的外观与交互。

    由 :class:`NumberBox` / :class:`DoubleNumberBox` 持有，
    在各自的``paintEvent`` / ``eventFilter`` / 鼠标事件里转调。
    取色走应用级 QPalette，颜色来源见 ThemeService 的 ROLE_SOURCES。
    """

    # 框线：圆角与 Card 同为 4px
    CORNER_RADIUS = 4
    BORDER_WIDTH = 1
    ACCENT_WIDTH = 2
    ACTIVE_STROKE_ALPHA = 0.4

    # 步进区
    STEPPER_WIDTH = 24
    STEPPER_ARM = 10
    STEPPER_WEIGHT = 2

    # 悬停与按压底板
    PLATE_SIZE = 20
    PLATE_RADIUS = 6
    PRESS_SINK = 1
    HOVER_ALPHA = 0.12
    PRESS_ALPHA = 0.28

    # 连发
    REPEAT_DELAY_MS = 400
    REPEAT_INTERVAL_MS = 80

    def __init__(self, owner: QAbstractSpinBox) -> None:
        """接管取值排布与内部编辑器的事件。

        Args:
            owner (QAbstractSpinBox): 承载字段外观的数值框。
        """
        self._owner = owner
        self._repeat = QTimer(owner)
        self._repeat.timeout.connect(self._repeat_step)
        owner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for editor in owner.findChildren(QLineEdit):
            editor.setMouseTracking(True)
            editor.installEventFilter(owner)

    # ── 事件 ────────────────────────────────────────────────────────

    def before_paint(self) -> None:
        """在取值绘制之前铺好填充、框线与底部灰线。"""
        self._paint_frame()

    def after_paint(self) -> None:
        """在取值绘制之后补上加减号。"""
        self._paint_steppers()

    def filter_editor(self, watched: QObject, event: QEvent) -> bool:
        """处置内部编辑器转来的事件。

        编辑器铺满整个控件，点击与悬停都归它：
        步进区的按压转为步进，悬停其上时光标切回箭头。

        Args:
            watched (QObject): 事件来源，即内部编辑器。
            event (QEvent): 转来的事件。

        Returns:
            bool: 已按步进区消费时为 ``True``。
        """
        if not isinstance(watched, QLineEdit) or not isinstance(event, QMouseEvent):
            return False
        pos = self._owner.mapFromGlobal(event.globalPosition().toPoint())
        if event.type() == QEvent.Type.MouseButtonPress:
            self._owner.update()
            return self._step(pos.x(), pos.y())
        if event.type() == QEvent.Type.MouseButtonRelease:
            self._stop_repeat()
        if event.type() == QEvent.Type.MouseMove:
            watched.setCursor(
                Qt.CursorShape.ArrowCursor
                if self._hit(pos.x(), pos.y())
                else Qt.CursorShape.IBeamCursor
            )
        if event.type() in (
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
        ):
            self._owner.update()
        return False

    def on_press(self, event: QMouseEvent) -> bool:
        """按压落在步进区时走一步。

        Args:
            event (QMouseEvent): 鼠标按压事件。

        Returns:
            bool: 已按步进区消费时为 ``True``。
        """
        pos = event.position().toPoint()
        self._owner.update()
        return self._step(pos.x(), pos.y())

    def on_release(self) -> None:
        """松开后停掉连发并重绘。"""
        self._stop_repeat()
        self._owner.update()

    # ── 步进区 ──────────────────────────────────────────────────────

    def _zones(self) -> tuple[QRect, QRect]:
        """返回左右步进区的命中矩形。

        Returns:
            tuple[QRect, QRect]: 左侧减号区与右侧加号区。
        """
        rect = self._owner.rect()
        height = rect.height()
        return (
            QRect(rect.left(), rect.top(), self.STEPPER_WIDTH, height),
            QRect(rect.right() - self.STEPPER_WIDTH + 1, rect.top(), self.STEPPER_WIDTH, height),
        )

    def _hit(self, x: int, y: int) -> int:
        """返回命中位置的步进方向，未命中为 0。

        Args:
            x (int): 鼠标位置的横坐标，控件局部坐标。
            y (int): 鼠标位置的纵坐标，控件局部坐标。

        Returns:
            int: 减号区为 -1，加号区为 1，其余为 0。
        """
        left, right = self._zones()
        if left.contains(x, y):
            return -1
        if right.contains(x, y):
            return 1
        return 0

    def _over(self) -> int:
        """返回指针所在的步进方向，不在步进区为 0。

        Returns:
            int: 减号区为 -1，加号区为 1，其余为 0。
        """
        pos = self._owner.mapFromGlobal(QCursor.pos())
        return self._hit(pos.x(), pos.y())

    def _down(self) -> int:
        """返回当前按压中的步进方向，无按压为 0。

        Returns:
            int: 按住减号区为 -1，按住加号区为 1，其余为 0。
        """
        if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            return 0
        return self._over()

    def _step(self, x: int, y: int) -> bool:
        """命中步进区时走一步，并启动连发。

        Args:
            x (int): 鼠标位置的横坐标，控件局部坐标。
            y (int): 鼠标位置的纵坐标，控件局部坐标。

        Returns:
            bool: 命中步进区并已步进时为 ``True``。
        """
        direction = self._hit(x, y)
        if not direction:
            return False
        self._owner.stepBy(direction)
        self._repeat.start(self.REPEAT_DELAY_MS)
        return True

    def _repeat_step(self) -> None:
        """连发一拍：仍按在步进区上才继续。"""
        direction = self._down()
        if not direction:
            return
        self._owner.stepBy(direction)
        self._repeat.setInterval(self.REPEAT_INTERVAL_MS)

    def _stop_repeat(self) -> None:
        """停掉连发。"""
        self._repeat.stop()

    # ── 绘制 ────────────────────────────────────────────────────────

    def _palette(self) -> QPalette:
        """返回应用级调色板。

        Returns:
            QPalette: 主题调色板。
        """
        app = QApplication.instance()
        return app.palette() if isinstance(app, QApplication) else self._owner.palette()

    def _paint_frame(self) -> None:
        """按控件状态绘制字段边框。"""
        owner = self._owner
        palette = self._palette()
        rect = QRectF(owner.rect())

        enabled = owner.isEnabled()
        focused = enabled and owner.hasFocus()
        active = focused or (enabled and owner.underMouse())

        mid = palette.color(QPalette.ColorRole.Mid)
        strong = QColor(palette.color(QPalette.ColorRole.PlaceholderText))
        strong.setAlphaF(self.ACTIVE_STROKE_ALPHA)
        faint = QColor(mid)
        faint.setAlphaF(faint.alphaF() * 0.5)

        fill = palette.color(
            QPalette.ColorRole.Base
            if (enabled and not active)
            else QPalette.ColorRole.Button
        )
        frame_stroke = strong if active else faint
        line_color = strong if active else mid

        painter = QPainter(owner)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        metrics = _PaintMetrics(painter)

        frame = metrics.aligned_stroke(rect, self.BORDER_WIDTH)
        path = QPainterPath()
        path.addRoundedRect(frame.rect, self.CORNER_RADIUS, self.CORNER_RADIUS)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawPath(path)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(frame_stroke, frame.width))
        painter.drawPath(path)

        if focused:
            line_color = palette.color(QPalette.ColorRole.Accent)
            line_width = self.ACCENT_WIDTH
        else:
            line_width = self.BORDER_WIDTH
        line = metrics.aligned_stroke(rect, line_width)

        pen = QPen(line_color, line.width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        y = line.rect.bottom()
        painter.drawLine(
            QLineF(
                frame.rect.left() + self.CORNER_RADIUS,
                y,
                frame.rect.right() - self.CORNER_RADIUS,
                y,
            )
        )

    def _paint_steppers(self) -> None:
        """悬停或聚焦时在左右步进区绘制减号与加号。"""
        owner = self._owner
        if not (owner.isEnabled() and (owner.hasFocus() or owner.underMouse())):
            return

        color = self._palette().color(QPalette.ColorRole.PlaceholderText)
        plate_color = QColor(color)
        down = self._down()
        over = self._over()

        painter = QPainter(owner)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(color, self.STEPPER_WEIGHT)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        half = self.STEPPER_ARM / 2
        left, right = self._zones()
        for direction, zone, vertical in ((-1, left, False), (1, right, True)):
            cx = zone.x() + zone.width() / 2
            cy = zone.y() + zone.height() / 2
            if direction == down:
                alpha = self.PRESS_ALPHA
            else:
                alpha = self.HOVER_ALPHA if direction == over else 0.0
            if alpha:
                plate_color.setAlphaF(alpha)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(plate_color)
                painter.drawRoundedRect(
                    QRectF(
                        cx - self.PLATE_SIZE / 2,
                        cy - self.PLATE_SIZE / 2,
                        self.PLATE_SIZE,
                        self.PLATE_SIZE,
                    ),
                    self.PLATE_RADIUS,
                    self.PLATE_RADIUS,
                )
                painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen)
            gy = cy + (self.PRESS_SINK if direction == down else 0)
            painter.drawLine(QLineF(cx - half, gy, cx + half, gy))
            if vertical:
                painter.drawLine(QLineF(cx, gy - half, cx, gy + half))


class NumberBox(QSpinBox):
    """整数数值框

    取值规则沿用 :class:`QSpinBox`。
    数字居中，左右为步进区，悬停或聚焦时复现加减号，点按各走一步，按住连发。

    Typical usage example::

        self.burst_size = NumberBox()
        self.burst_size.setRange(2, 100)
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chrome = _FieldChrome(self)

    def paintEvent(self, event: QPaintEvent) -> None:
        self._chrome.before_paint()
        super().paintEvent(event)
        self._chrome.after_paint()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if self._chrome.filter_editor(watched, event):
            return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._chrome.on_press(event):
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._chrome.on_release()
        super().mouseReleaseEvent(event)


class DoubleNumberBox(QDoubleSpinBox):
    """小数数值框

    取值规则沿用 :class:`QDoubleSpinBox`。
    数字居中，左右为步进区，悬停或聚焦时复现加减号，点按各走一步，按住连发。

    Typical usage example::

        self.min_delay = DoubleNumberBox()
        self.min_delay.setRange(0.1, 60.0)
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chrome = _FieldChrome(self)

    def paintEvent(self, event: QPaintEvent) -> None:
        self._chrome.before_paint()
        super().paintEvent(event)
        self._chrome.after_paint()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if self._chrome.filter_editor(watched, event):
            return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._chrome.on_press(event):
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._chrome.on_release()
        super().mouseReleaseEvent(event)
