"""字段输入框的边框绘制。

仿 Fluent-Qt 的字段处理：圆角填充、细框、底部灰线，聚焦时底部灰线换为强调色。
底部灰线不沿周长描边，而是两端各内缩一个圆角半径的圆头短线。
笔画与外框按设备像素对齐，高 DPI 下边缘不发虚。
取色走应用级 QPalette，颜色来源见 ThemeService 的 ROLE_SOURCES。
"""

import math
from typing import NamedTuple

from PySide6.QtCore import QLineF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QSpinBox, QWidget

# 与 Card 同为 4px 控件圆角
CORNER_RADIUS = 4
# 常态描边宽度
BORDER_WIDTH = 1
# 聚焦强调线宽度
ACCENT_WIDTH = 2


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


def _paint_frame(widget: QWidget) -> None:
    """按控件状态绘制字段边框。

    Args:
        widget (QWidget): 被绘制的输入控件。
    """
    # 取应用级调色板：widget.palette() 在 QSS 作用下会被改写，Base 等角色会失真
    app = QApplication.instance()
    palette = app.palette() if isinstance(app, QApplication) else widget.palette()
    rect = QRectF(widget.rect())

    enabled = widget.isEnabled()
    focused = enabled and widget.hasFocus()
    active = focused or (enabled and widget.underMouse())

    stroke = palette.color(QPalette.ColorRole.Mid)
    fill = palette.color(QPalette.ColorRole.Base if enabled else QPalette.ColorRole.Button)

    # 常态框线取描边色的半透明，使其浅于底部灰线
    frame_stroke = QColor(stroke)
    if not active:
        frame_stroke.setAlphaF(frame_stroke.alphaF() * 0.5)

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

    # 底部灰线：聚焦转强调色并加粗，其余取描边色本色——它比框线更实
    line_color = palette.color(QPalette.ColorRole.Accent) if focused else stroke
    line_width = ACCENT_WIDTH if focused else BORDER_WIDTH
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
    """整数数值框，外观取自 Fluent-Qt NumberBox 的默认档。

    只负责边框外观，取值规则沿用 :class:`QSpinBox`。
    步进按钮不绘制，取值用输入、滚轮或方向键。

    Typical usage example::

        self.burst_size = NumberBox()
        self.burst_size.setRange(2, 100)
    """

    def paintEvent(self, event: QPaintEvent) -> None:
        _paint_frame(self)
        super().paintEvent(event)


class DoubleNumberBox(QDoubleSpinBox):
    """小数数值框，外观取自 Fluent-Qt NumberBox 的默认档。

    只负责边框外观，取值规则沿用 :class:`QDoubleSpinBox`。
    步进按钮不绘制，取值用输入、滚轮或方向键。

    Typical usage example::

        self.min_delay = DoubleNumberBox()
        self.min_delay.setRange(0.1, 60.0)
    """

    def paintEvent(self, event: QPaintEvent) -> None:
        _paint_frame(self)
        super().paintEvent(event)
