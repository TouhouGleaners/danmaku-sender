"""字段输入框的边框与步进区绘制。

仿 Fluent-Qt 的字段处理：圆角填充、细框、底部灰线，聚焦时底部灰线换为强调色。
底部灰线不沿周长描边，而是两端各内缩一个圆角半径的圆头短线。
取值居中，左右留出步进区，悬停或聚焦时复现加减号。
笔画与外框按设备像素对齐，高 DPI 下边缘不发虚。
取色走应用级 QPalette，颜色来源见 ThemeService 的 ROLE_SOURCES。
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

# 与 Card 同为 4px 控件圆角
CORNER_RADIUS = 4
# 常态描边宽度
BORDER_WIDTH = 1
# 聚焦强调线宽度
ACCENT_WIDTH = 2
# 左右步进区宽度。控件宽度由 Qt 按 min/max 取值算出，比字宽加内边距宽得多，
# 文字居中后与符号之间自留余量，故不必与 style.qss 的 padding 相等。
STEPPER_WIDTH = 24
# 加减号的臂长与笔画粗细
STEPPER_ARM = 10
STEPPER_WEIGHT = 2
# 底板的边长、圆角与按压下沉量
STEPPER_PLATE = 20
STEPPER_PLATE_RADIUS = 6
STEPPER_PRESS_SINK = 1
# 悬停与按压底板分别取 text_secondary 的两档
STEPPER_HOVER_ALPHA = 0.12
STEPPER_PRESS_ALPHA = 0.28
# 按住后的停顿时长与连发间隔
REPEAT_DELAY_MS = 400
REPEAT_INTERVAL_MS = 80
# 加重描边取 text_secondary 的四成，深浅两档都朝对比更强处走
ACTIVE_STROKE_ALPHA = 0.4
# 连发计时器的对象名，用于从控件上取回
_REPEAT_NAME = "stepperRepeat"


def _qround(value: float) -> int:
    """按 Qt 的 qRound 取整，半数远离零。

    Args:
        value (float): 待取整的数值。

    Returns:
        int: 取整结果。
    """
    return int(value + 0.5) if value >= 0 else int(value - 0.5)


class _Stroke(NamedTuple):
    """对齐到设备像素后的描边矩形与笔宽。"""

    rect: QRectF
    width: float


class _PaintMetrics:
    """把矩形与笔画对齐到设备像素。

    以画笔的 ``deviceTransform`` 为准，它同时覆盖高 DPI 缩放、
    重定向绘制与小数位移。Qt 仍掌管逻辑几何，本类只负责压齐像素。

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
        left = _qround(device.left())
        top = _qround(device.top())
        right = max(left, _qround(device.right()))
        bottom = max(top, _qround(device.bottom()))
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
        physical = max(1, _qround(width * self._scale_x))
        inset = physical / 2
        device.adjust(inset, inset, -inset, -inset)
        inverted, ok = self._transform.inverted()
        aligned = inverted.mapRect(device).normalized() if ok else fallback
        return _Stroke(aligned, physical / self._scale_x)


def _app_palette(widget: QWidget) -> QPalette:
    """返回应用级调色板。

    ``widget.palette()`` 在 QSS 作用下会被改写，``Base`` 等角色会失真，
    因此主题色一律取 ``ThemeService`` 写入的应用级那份。

    Args:
        widget (QWidget): 无应用实例时的回退调色板来源。

    Returns:
        QPalette: 可用的主题调色板。
    """
    app = QApplication.instance()
    return app.palette() if isinstance(app, QApplication) else widget.palette()


def _stepper_zones(widget: QWidget) -> tuple[QRect, QRect]:
    """返回左右步进区的命中矩形。

    Args:
        widget (QWidget): 承载步进区的输入控件。

    Returns:
        tuple[QRect, QRect]: 左侧减号区与右侧加号区。
    """
    rect = widget.rect()
    height = rect.height()
    return (
        QRect(rect.left(), rect.top(), STEPPER_WIDTH, height),
        QRect(rect.right() - STEPPER_WIDTH + 1, rect.top(), STEPPER_WIDTH, height),
    )


def _install_stepper(widget: QAbstractSpinBox) -> None:
    """改为居中取值，步进区交给自绘加减号。

    原生步进按钮不走 ``NoButtons``：控件一旦挂上 QSS，``NoButtons``
    会让 ``drawComplexControl`` 整段跳过、连取值一起画不出来。
    改由 ``style.qss`` 把 ``::up-button`` / ``::down-button`` 压成 0。

    内部编辑器铺满整个控件，点击与悬停都归它；这里挂上事件过滤器，
    把落在步进区的按压转回步进，并按位置切换光标。

    Args:
        widget (QAbstractSpinBox): 待改造的数值框。
    """
    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    timer = QTimer(widget)
    timer.setObjectName(_REPEAT_NAME)
    timer.timeout.connect(lambda: _stepper_repeat(widget))
    for editor in widget.findChildren(QLineEdit):
        editor.setMouseTracking(True)
        editor.installEventFilter(widget)


def _stepper_filter(widget: QAbstractSpinBox, watched: QObject, event: QEvent) -> bool:
    """处置内部编辑器转来的事件。

    编辑器自带 I-beam 光标，铺满控件后连步进区一起变回「文本区」；
    悬停其上时按位置把光标切回箭头，与按钮语义一致。

    Args:
        widget (QAbstractSpinBox): 数值框。
        watched (QObject): 事件来源，即内部编辑器。
        event (QEvent): 转来的事件。

    Returns:
        bool: 已按步进区消费时为 ``True``。
    """
    if not isinstance(watched, QLineEdit) or not isinstance(event, QMouseEvent):
        return False
    pos = widget.mapFromGlobal(event.globalPosition().toPoint())
    if event.type() == QEvent.Type.MouseButtonPress:
        widget.update()
        return _stepper_step(widget, pos.x(), pos.y())
    if event.type() == QEvent.Type.MouseButtonRelease:
        _stepper_release(widget)
    if event.type() == QEvent.Type.MouseMove:
        shape = (
            Qt.CursorShape.ArrowCursor
            if _stepper_hit(widget, pos.x(), pos.y())
            else Qt.CursorShape.IBeamCursor
        )
        watched.setCursor(shape)
    if event.type() in (
        QEvent.Type.MouseMove,
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonRelease,
    ):
        widget.update()
    return False


def _stepper_over(widget: QWidget) -> int:
    """返回指针所在的步进方向，不在步进区为 0。

    Args:
        widget (QWidget): 承载步进区的输入控件。

    Returns:
        int: 减号区为 -1，加号区为 1，其余为 0。
    """
    pos = widget.mapFromGlobal(QCursor.pos())
    return _stepper_hit(widget, pos.x(), pos.y())


def _stepper_pressed(widget: QWidget) -> int:
    """返回当前按压中的步进方向，无按压为 0。

    不记状态，按全局按键与指针位置现算，省掉方法间的可变标志。

    Args:
        widget (QWidget): 数值框。

    Returns:
        int: 按住减号区为 -1，按住加号区为 1，其余为 0。
    """
    if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
        return 0
    return _stepper_over(widget)


def _paint_steppers(widget: QWidget) -> None:
    """悬停或聚焦时在左右步进区绘制减号与加号。

    指针落在某一侧时浮出浅底板，按压再加深并让符号下沉一步。

    Args:
        widget (QWidget): 被绘制的输入控件。
    """
    if not (widget.isEnabled() and (widget.hasFocus() or widget.underMouse())):
        return

    palette = _app_palette(widget)
    color = palette.color(QPalette.ColorRole.PlaceholderText)
    plate_color = QColor(color)
    down = _stepper_pressed(widget)
    over = _stepper_over(widget)

    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, STEPPER_WEIGHT)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)

    half = STEPPER_ARM / 2
    left, right = _stepper_zones(widget)
    for direction, zone, vertical in ((-1, left, False), (1, right, True)):
        # 不用 QRect.center()：整数截断会让左右到边距差 2px
        cx = zone.x() + zone.width() / 2
        cy = zone.y() + zone.height() / 2
        if direction == down:
            alpha = STEPPER_PRESS_ALPHA
        else:
            alpha = STEPPER_HOVER_ALPHA if direction == over else 0.0
        if alpha:
            plate_color.setAlphaF(alpha)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(plate_color)
            painter.drawRoundedRect(
                QRectF(
                    cx - STEPPER_PLATE / 2,
                    cy - STEPPER_PLATE / 2,
                    STEPPER_PLATE,
                    STEPPER_PLATE,
                ),
                STEPPER_PLATE_RADIUS,
                STEPPER_PLATE_RADIUS,
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        gy = cy + (STEPPER_PRESS_SINK if direction == down else 0)
        painter.drawLine(QLineF(cx - half, gy, cx + half, gy))
        if vertical:
            painter.drawLine(QLineF(cx, gy - half, cx, gy + half))


def _stepper_hit(widget: QWidget, x: int, y: int) -> int:
    """返回命中位置的步进方向，未命中为 0。

    Args:
        widget (QWidget): 承载步进区的输入控件。
        x (int): 鼠标位置的横坐标，控件局部坐标。
        y (int): 鼠标位置的纵坐标，控件局部坐标。

    Returns:
        int: 减号区为 -1，加号区为 1，其余为 0。
    """
    left, right = _stepper_zones(widget)
    if left.contains(x, y):
        return -1
    if right.contains(x, y):
        return 1
    return 0


def _stepper_step(widget: QAbstractSpinBox, x: int, y: int) -> bool:
    """命中步进区时走一步。

    Args:
        widget (QAbstractSpinBox): 数值框。
        x (int): 鼠标位置的横坐标，控件局部坐标。
        y (int): 鼠标位置的纵坐标，控件局部坐标。

    Returns:
        bool: 命中步进区并已步进时为 ``True``。
    """
    direction = _stepper_hit(widget, x, y)
    if not direction:
        return False
    widget.stepBy(direction)
    timer = widget.findChild(QTimer, _REPEAT_NAME)
    if timer is not None:
        timer.start(REPEAT_DELAY_MS)
    return True


def _stepper_repeat(widget: QAbstractSpinBox) -> None:
    """连发一拍：仍按在步进区上才继续。

    方向不记状态，按全局按键与指针位置现算。

    Args:
        widget (QAbstractSpinBox): 数值框。
    """
    direction = _stepper_pressed(widget)
    if not direction:
        return
    widget.stepBy(direction)
    timer = widget.findChild(QTimer, _REPEAT_NAME)
    if timer is not None:
        timer.setInterval(REPEAT_INTERVAL_MS)


def _stepper_release(widget: QAbstractSpinBox) -> None:
    """松开后停掉连发。

    Args:
        widget (QAbstractSpinBox): 数值框。
    """
    timer = widget.findChild(QTimer, _REPEAT_NAME)
    if timer is not None:
        timer.stop()


def _paint_frame(widget: QWidget) -> None:
    """按控件状态绘制字段边框。

    Args:
        widget (QWidget): 被绘制的输入控件。
    """
    palette = _app_palette(widget)
    rect = QRectF(widget.rect())

    enabled = widget.isEnabled()
    focused = enabled and widget.hasFocus()
    active = focused or (enabled and widget.underMouse())

    mid = palette.color(QPalette.ColorRole.Mid)
    strong = QColor(palette.color(QPalette.ColorRole.PlaceholderText))
    strong.setAlphaF(ACTIVE_STROKE_ALPHA)
    faint = QColor(mid)
    faint.setAlphaF(faint.alphaF() * 0.5)

    fill = palette.color(
        QPalette.ColorRole.Base if (enabled and not active) else QPalette.ColorRole.Button
    )
    frame_stroke = strong if active else faint
    # 底部灰线比框线实：常态取描边色本色，活跃时与框线同为加重描边
    line_color = strong if active else mid

    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    metrics = _PaintMetrics(painter)

    frame = metrics.aligned_stroke(rect, BORDER_WIDTH)
    path = QPainterPath()
    path.addRoundedRect(frame.rect, CORNER_RADIUS, CORNER_RADIUS)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    painter.drawPath(path)

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(frame_stroke, frame.width))
    painter.drawPath(path)

    # 聚焦时底部灰线转强调色并加粗
    if focused:
        line_color = palette.color(QPalette.ColorRole.Accent)
        line_width = ACCENT_WIDTH
    else:
        line_width = BORDER_WIDTH
    line = metrics.aligned_stroke(rect, line_width)

    pen = QPen(line_color, line.width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    y = line.rect.bottom()
    painter.drawLine(
        QLineF(
            frame.rect.left() + CORNER_RADIUS,
            y,
            frame.rect.right() - CORNER_RADIUS,
            y,
        )
    )


class NumberBox(QSpinBox):
    """整数数值框，外观取自 Fluent-Qt NumberBox 的默认档并加上自绘步进区。

    取值规则沿用 :class:`QSpinBox`。数字居中，左右为步进区，
    悬停或聚焦时复现加减号，点按各走一步。

    Typical usage example::

        self.burst_size = NumberBox()
        self.burst_size.setRange(2, 100)
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _install_stepper(self)

    def paintEvent(self, event: QPaintEvent) -> None:
        _paint_frame(self)
        super().paintEvent(event)
        _paint_steppers(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if _stepper_filter(self, watched, event):
            return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        self.update()
        if _stepper_step(self, pos.x(), pos.y()):
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        _stepper_release(self)
        self.update()
        super().mouseReleaseEvent(event)


class DoubleNumberBox(QDoubleSpinBox):
    """小数数值框，外观取自 Fluent-Qt NumberBox 的默认档并加上自绘步进区。

    取值规则沿用 :class:`QDoubleSpinBox`。数字居中，左右为步进区，
    悬停或聚焦时复现加减号，点按各走一步。

    Typical usage example::

        self.min_delay = DoubleNumberBox()
        self.min_delay.setRange(0.1, 60.0)
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _install_stepper(self)

    def paintEvent(self, event: QPaintEvent) -> None:
        _paint_frame(self)
        super().paintEvent(event)
        _paint_steppers(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if _stepper_filter(self, watched, event):
            return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        self.update()
        if _stepper_step(self, pos.x(), pos.y()):
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        _stepper_release(self)
        self.update()
        super().mouseReleaseEvent(event)
