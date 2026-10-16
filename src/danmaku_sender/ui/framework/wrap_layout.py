"""按可用宽度自动换行的布局。

把控件排成流式行，一行放不下时折到下一行。
用于尾部控件由多个小控件拼成、且要随设置行宽度伸缩的场景。

Typical usage example::

    box = QWidget()
    layout = WrapLayout(box, spacing=6)
    layout.addWidget(QCheckBox("启用"))
    layout.addWidget(QSpinBox())
    layout.addWidget(QLabel("秒"))
"""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class WrapLayout(QLayout):
    """流式换行布局，高度随可用宽度变化。

    Attributes:
        无公开属性，控件经 ``addWidget`` 挂载。

    Typical usage example::

        box = QWidget()
        layout = WrapLayout(box, spacing=6)
        layout.addWidget(control_a)
        layout.addWidget(control_b)
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        margin: int = 0,
        spacing: int = 0,
    ):
        """初始化布局。

        Args:
            parent (QWidget | None): 承载本布局的控件。
            margin (int): 四边内边距。
            spacing (int): 控件之间的间距。
        """
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        """按给定宽度计算排版所需高度。

        Args:
            width (int): 可用宽度。

        Returns:
            int: 排版所需高度。
        """
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        self._do_layout(rect, apply=True)
        super().setGeometry(rect)

    def minimumSize(self) -> QSize:
        """最宽单项的尺寸，保证每行至少放得下一个控件。

        Returns:
            QSize: 最小可用尺寸。
        """
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return QSize(
            size.width() + margins.left() + margins.right(),
            size.height() + margins.top() + margins.bottom(),
        )

    def sizeHint(self) -> QSize:
        """单行排开时的自然尺寸。

        Returns:
            QSize: 不折行所需的尺寸。
        """
        width = 0
        height = 0
        spacing = self.spacing()
        for index, item in enumerate(self._items):
            hint = item.sizeHint()
            width += hint.width() + (spacing if index else 0)
            height = max(height, hint.height())
        margins = self.contentsMargins()
        return QSize(
            width + margins.left() + margins.right(),
            height + margins.top() + margins.bottom(),
        )

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        """排布各控件，宽度不足时折行。

        Args:
            rect (QRect): 可用区域。
            apply (bool): 为 ``False`` 时只计算高度，不写入几何。

        Returns:
            int: 排版实际占用的底边坐标。
        """
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        right_edge = effective.x() + effective.width()
        x = effective.x()
        y = effective.y()
        line_height = 0
        spacing = self.spacing()

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > right_edge and line_height > 0:
                x = effective.x()
                y += line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if apply:
                item.setGeometry(QRect(x, y, hint.width(), hint.height()))
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + margins.bottom()
