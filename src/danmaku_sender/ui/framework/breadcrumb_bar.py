"""路径式导航条，按段展示当前位置并支持回溯。

段与段之间以 chevron 分隔，末段表示当前位置，其余段可点击回溯。
悬停反馈仅作用于文字颜色，不绘制底板，光标保持箭头。
外观自绘，配色取自应用级 QPalette，来源见 ThemeService 的 ROLE_SOURCES。
"""

from typing import NamedTuple

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QEnterEvent,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import QApplication, QWidget


class BreadcrumbBar(QWidget):
    """路径式导航条。

    Attributes:
        itemActivated (Signal(int)): 点击可回溯段时发射，参数为段下标。
    """

    itemActivated = Signal(int)

    # 文字
    ROW_HEIGHT = 40
    FONT_SIZE = 28
    FONT_WEIGHT = QFont.Weight.Normal

    # 段与分隔槽
    ITEM_PADDING = 8
    SEPARATOR_WIDTH = 24

    # 分隔 chevron 折线
    CHEVRON_WIDTH = 7
    CHEVRON_HEIGHT = 11
    CHEVRON_WEIGHT = 2

    class _Record(NamedTuple):
        """一个绘制单元。

        Attributes:
            index (int | None): 段下标；分隔槽为 ``None``。
            rect (QRectF): 命中矩形。
        """

        index: int | None
        rect: QRectF

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化导航条。

        Args:
            parent (QWidget | None): 父控件。
        """
        super().__init__(parent)
        self._items: list[str] = []
        self._records: list[BreadcrumbBar._Record] = []
        self._hovered: int | None = None
        self.setMouseTracking(True)
        self.setFixedHeight(self.ROW_HEIGHT)

    def setItems(self, items: list[str]) -> None:
        """设置路径段。

        Args:
            items (list[str]): 自根至当前的段文本。
        """
        self._items = list(items)
        self._hovered = None
        self._records = self._layout_records()
        self.updateGeometry()
        self.update()

    def items(self) -> list[str]:
        """返回路径段。

        Returns:
            list[str]: 自根至当前的段文本。
        """
        return list(self._items)

    def sizeHint(self) -> QSize:
        """返回按内容量算的尺寸。

        Returns:
            QSize: 宽度为各段与分隔槽的合计，高度为行高。
        """
        return QSize(round(self._content_width()), self.ROW_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        """返回最小尺寸。

        Returns:
            QSize: 高度固定为行高，宽度不限。
        """
        return QSize(0, self.ROW_HEIGHT)

    # ── 排布 ────────────────────────────────────────────────────────

    def _layout_records(self) -> list[_Record]:
        """按当前路径排布段与分隔槽的矩形。

        Returns:
            list[_Record]: 自左至右的绘制单元。
        """
        metrics = QFontMetrics(self._font())
        records: list[BreadcrumbBar._Record] = []
        x = 0.0
        last = len(self._items) - 1
        for i, text in enumerate(self._items):
            width = metrics.horizontalAdvance(text) + 2 * self.ITEM_PADDING
            records.append(self._Record(i, QRectF(x, 0, width, self.ROW_HEIGHT)))
            x += width
            if i < last:
                records.append(
                    self._Record(None, QRectF(x, 0, self.SEPARATOR_WIDTH, self.ROW_HEIGHT))
                )
                x += self.SEPARATOR_WIDTH
        return records

    def _content_width(self) -> float:
        """返回内容合计宽度。

        Returns:
            float: 最后一个绘制单元的右缘；无内容时为 0。
        """
        return self._records[-1].rect.right() if self._records else 0.0

    def _font(self) -> QFont:
        """返回段文字使用的字体。

        Returns:
            QFont: 全局字体族上覆写页头字号与字重后的字体。
        """
        font = QFont(self.font())
        font.setPixelSize(self.FONT_SIZE)
        font.setWeight(self.FONT_WEIGHT)
        return font

    def _hit(self, pos: QPointF) -> int | None:
        """返回可回溯段的下标。

        Args:
            pos (QPointF): 控件坐标系下的指针位置。

        Returns:
            int | None: 落在可回溯段内时为该段下标，否则为 ``None``。
        """
        last = len(self._items) - 1
        for record in self._records:
            if record.index is None or not record.rect.contains(pos):
                continue
            return record.index if record.index < last else None
        return None

    def _palette(self) -> QPalette:
        """返回应用级调色板。

        Returns:
            QPalette: 主题调色板。
        """
        app = QApplication.instance()
        return app.palette() if isinstance(app, QApplication) else self.palette()

    # ── 事件 ────────────────────────────────────────────────────────

    def enterEvent(self, event: QEnterEvent) -> None:
        """指针进入时按落点更新悬停段。"""
        super().enterEvent(event)
        self._update_hover(event.position())

    def leaveEvent(self, event: QEvent) -> None:
        """指针离开时清除悬停段。"""
        super().leaveEvent(event)
        self._set_hover(None)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """指针移动时更新悬停段与光标形状。"""
        super().mouseMoveEvent(event)
        self._update_hover(event.position())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """点击可回溯段时发出激活信号。"""
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._hit(event.position())
            if index is not None:
                self.itemActivated.emit(index)
                event.accept()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制各段文字与分隔 chevron。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = self._font()
        palette = self._palette()
        main = palette.color(QPalette.ColorRole.WindowText)
        secondary = palette.color(QPalette.ColorRole.PlaceholderText)
        last = len(self._items) - 1

        for record in self._records:
            if record.index is None:
                self._paint_chevron(painter, record.rect, secondary)
                continue
            if record.index == last:
                painter.setPen(main)
            else:
                painter.setPen(main if self._hovered == record.index else secondary)
            painter.setFont(font)
            painter.drawText(
                record.rect.adjusted(self.ITEM_PADDING, 0, -self.ITEM_PADDING, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                self._items[record.index],
            )

    def _paint_chevron(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        """绘制分隔 chevron 折线。

        Args:
            painter (QPainter): 正在绘制的画笔。
            rect (QRectF): 分隔槽的矩形。
            color (QColor): 折线颜色。
        """
        cx = rect.x() + rect.width() / 2
        cy = rect.y() + rect.height() / 2
        half_w = self.CHEVRON_WIDTH / 2
        half_h = self.CHEVRON_HEIGHT / 2

        path = QPainterPath()
        path.moveTo(cx - half_w, cy - half_h)
        path.lineTo(cx + half_w, cy)
        path.lineTo(cx - half_w, cy + half_h)

        pen = QPen(color, self.CHEVRON_WEIGHT)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _update_hover(self, pos: QPointF) -> None:
        """按指针位置更新悬停段。

        光标始终保持箭头，不改为手型。

        Args:
            pos (QPointF): 控件坐标系下的指针位置。
        """
        self._set_hover(self._hit(pos))

    def _set_hover(self, index: int | None) -> None:
        """记录悬停段并在变化时触发重绘。

        Args:
            index (int | None): 悬停段下标；无悬停段时为 ``None``。
        """
        if self._hovered == index:
            return
        self._hovered = index
        self.update()
