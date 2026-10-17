"""字段输入框的外框与步进区。

字段外观由圆角填充、外框与底部灰线组成，聚焦时底部灰线改用强调色。
底部灰线为独立绘制的圆头短线，两端各内缩一个圆角半径，不随外框环绕。
取值居中，左右两侧为步进区，悬停或聚焦时显示加减号。
笔画与外框对齐至设备像素，在高 DPI 缩放下保持边缘清晰。
"""

import math
from typing import NamedTuple

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QLineF,
    QObject,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
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
    """对齐至设备像素后的描边矩形与笔宽。"""

    rect: QRectF
    width: float


class _PaintMetrics:
    """将矩形与笔画对齐至设备像素。

    以画笔的 ``deviceTransform`` 为基准，该变换同时涵盖高 DPI 缩放、重定向绘制与小数位移。

    Typical usage example::

        metrics = _PaintMetrics(painter)
        stroke = metrics.aligned_stroke(widget.rect(), 1.0)
    """

    def __init__(self, painter: QPainter) -> None:
        """读取画笔的设备变换并判定是否可对齐。

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
        """按 ``qRound`` 语义取整，中值取远离零的一侧。

        Args:
            value (float): 待取整的数值。

        Returns:
            int: 取整结果。
        """
        return int(value + 0.5) if value >= 0 else int(value - 0.5)

    def aligned_outer_rect(self, rect: QRectF) -> QRectF:
        """将逻辑矩形的四边对齐至设备像素。

        Args:
            rect (QRectF): 逻辑坐标下的矩形。

        Returns:
            QRectF: 对齐后的逻辑矩形。
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
        """返回对齐至设备像素的描边矩形与笔宽。

        Args:
            rect (QRectF): 逻辑坐标下的外框矩形。
            width (float): 逻辑笔宽。

        Returns:
            _Stroke: 对齐后的描边矩形与笔宽；笔宽非正时宽度为 0。
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


class _Reveal:
    """浮层元素的渐显进度，取值 0 到 1。

    Typical usage example::

        reveal = _Reveal(widget)
        reveal.target(1.0)
        alpha = reveal.value()
    """

    # 渐显时长
    FADE_MS = 150

    def __init__(self, owner: QWidget) -> None:
        """建立渐显进度，变化时重绘所属控件。

        Args:
            owner (QWidget): 受渐显影响的控件。
        """
        self._owner = owner
        self._value = 0.0
        self._anim = QVariantAnimation(owner)
        self._anim.setDuration(self.FADE_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._accept)

    def value(self) -> float:
        """返回当前渐显进度。

        Returns:
            float: 0 到 1 之间的进度值。
        """
        return self._value

    def target(self, goal: float) -> None:
        """将渐显进度推向目标值。

        Args:
            goal (float): 目标进度，取值 0 到 1。
        """
        if abs(self._value - goal) < 1e-6:
            return
        if (
            self._anim.state() != QAbstractAnimation.State.Stopped
            and self._anim.endValue() == goal
        ):
            return
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(goal)
        self._anim.start()

    def _accept(self, value: float) -> None:
        self._value = float(value)
        self._owner.update()


class _FieldChrome:
    """字段外框与步进区的外观与交互。

    由 :class:`NumberBox` / :class:`DoubleNumberBox` 持有，
    在各自的 ``paintEvent`` / ``eventFilter`` 与鼠标事件中转调。
    配色取自应用级 QPalette，来源见 ThemeService 的 ROLE_SOURCES。
    """

    # 外框，圆角与 Card 一致为 4px
    CORNER_RADIUS = 4
    BORDER_WIDTH = 1
    ACCENT_WIDTH = 2
    ACTIVE_STROKE_ALPHA = 0.4

    # 步进区
    STEPPER_WIDTH = 24
    STEPPER_ARM = 10
    STEPPER_WEIGHT = 2

    # 步进区的悬停与按压底板
    PLATE_SIZE = 20
    PLATE_RADIUS = 6
    PRESS_SINK = 1
    HOVER_ALPHA = 0.12
    PRESS_ALPHA = 0.28

    # 连续步进时序
    REPEAT_DELAY_MS = 400
    REPEAT_INTERVAL_MS = 80

    def __init__(self, owner: QAbstractSpinBox) -> None:
        """接管取值排布，并安装内部编辑器的事件过滤器。

        Args:
            owner (QAbstractSpinBox): 承载字段外观的数值框。
        """
        self._owner = owner
        self._repeat = QTimer(owner)
        self._repeat.timeout.connect(self._repeat_step)
        self._glyph_reveal = _Reveal(owner)
        self._plate_reveal = _Reveal(owner)
        owner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for editor in owner.findChildren(QLineEdit):
            editor.setMouseTracking(True)
            editor.installEventFilter(owner)

    # ── 事件 ────────────────────────────────────────────────────────

    def before_paint(self) -> None:
        """在取值绘制之前绘制填充、外框与底部灰线。"""
        self._paint_frame()

    def after_paint(self) -> None:
        """在取值绘制之后绘制加减号。"""
        self._sync_reveal()
        self._paint_steppers()

    def filter_editor(self, watched: QObject, event: QEvent) -> bool:
        """处理内部编辑器转发的事件。

        内部编辑器铺满整个控件，按压与悬停均由其接收：
        落在步进区的按压转为步进，悬停其上时将光标改为箭头。

        Args:
            watched (QObject): 事件来源，即内部编辑器。
            event (QEvent): 转发的事件。

        Returns:
            bool: 事件已由步进区消费时为 ``True``。
        """
        if not isinstance(watched, QLineEdit):
            return False
        if event.type() in (QEvent.Type.Enter, QEvent.Type.Leave):
            self._owner.update()
            return False
        if not isinstance(event, QMouseEvent):
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
        self._owner.update()
        return False

    def on_press(self, event: QMouseEvent) -> bool:
        """按压落在步进区时步进一步。

        Args:
            event (QMouseEvent): 鼠标按压事件。

        Returns:
            bool: 事件已由步进区消费时为 ``True``。
        """
        pos = event.position().toPoint()
        self._owner.update()
        return self._step(pos.x(), pos.y())

    def on_release(self) -> None:
        """松开后停止连续步进并重绘。"""
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
        """返回命中位置的步进方向，未命中返回 0。

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
        """返回指针所在的步进方向，不在步进区返回 0。

        Returns:
            int: 减号区为 -1，加号区为 1，其余为 0。
        """
        pos = self._owner.mapFromGlobal(QCursor.pos())
        return self._hit(pos.x(), pos.y())

    def _down(self) -> int:
        """返回当前按压的步进方向，无按压返回 0。

        Returns:
            int: 按住减号区为 -1，按住加号区为 1，其余为 0。
        """
        if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            return 0
        return self._over()

    def _step(self, x: int, y: int) -> bool:
        """命中步进区时步进一步，并启动连续步进。

        Args:
            x (int): 鼠标位置的横坐标，控件局部坐标。
            y (int): 鼠标位置的纵坐标，控件局部坐标。

        Returns:
            bool: 事件已由步进区消费时为 ``True``。
        """
        direction = self._hit(x, y)
        if not direction:
            return False
        self._owner.stepBy(direction)
        self._repeat.start(self.REPEAT_DELAY_MS)
        return True

    def _repeat_step(self) -> None:
        """连续步进一步；指针已离开步进区时跳过。"""
        direction = self._down()
        if not direction:
            return
        self._owner.stepBy(direction)
        self._repeat.setInterval(self.REPEAT_INTERVAL_MS)

    def _stop_repeat(self) -> None:
        """停止连续步进。"""
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
        """按控件状态绘制字段外框。"""
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

    def _sync_reveal(self) -> None:
        """按悬停与焦点状态推进渐显进度。"""
        owner = self._owner
        on = owner.isEnabled() and (owner.hasFocus() or owner.underMouse())
        self._glyph_reveal.target(1.0 if on else 0.0)
        self._plate_reveal.target(1.0 if (on and self._over()) else 0.0)

    def _paint_steppers(self) -> None:
        """悬停或聚焦时在左右步进区绘制加减号。"""
        owner = self._owner
        glyph_alpha = self._glyph_reveal.value()
        plate_reveal = self._plate_reveal.value()
        if glyph_alpha <= 0 or not owner.isEnabled():
            return

        base = self._palette().color(QPalette.ColorRole.PlaceholderText)
        color = QColor(base)
        color.setAlphaF(color.alphaF() * glyph_alpha)
        plate_color = QColor(base)
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
            alpha *= plate_reveal
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
    """整数数值框。

    取值规则沿用 :class:`QSpinBox`。
    取值居中，左右为步进区，悬停或聚焦时显示加减号；
    点按步进一步，按住连续加减。

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
    """小数数值框。

    取值规则沿用 :class:`QDoubleSpinBox`。
    取值居中，左右为步进区，悬停或聚焦时显示加减号；
    点按步进一步，按住连续加减。

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
