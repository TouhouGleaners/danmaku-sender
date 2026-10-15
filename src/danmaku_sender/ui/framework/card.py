"""Fluent 风格卡片容器。

非交互式表面，用于分组呈现调用方的内容。外观由 ``style.qss`` 的
``QFrame#card`` 规则绘制，本模块只负责维护外观属性。
"""

from enum import Enum

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class CardAppearance(Enum):
    """卡片的填充表面，对应表面层级。

    层级自底向上为 canvas → layer → layer_alt / overlay。
    """

    CANVAS = "canvas"
    LAYER = "layer"
    LAYER_ALT = "alt"
    OVERLAY = "overlay"


class Card(QFrame):
    """圆角卡片容器，子控件由调用方的布局管理。

    Attributes:
        title_label: 标题控件；未提供标题时为 ``None``。
    """

    def __init__(self, title: str | None = None, parent: QWidget | None = None):
        """初始化卡片。

        Args:
            title: 卡片标题；为空则不显示标题行。
            parent: 父控件。
        """
        super().__init__(parent)
        self.setObjectName("card")
        self.setProperty("appearance", CardAppearance.LAYER.value)
        self.setProperty("border", "true")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 16)
        self._layout.setSpacing(10)

        self.title_label: QLabel | None = None
        if title:
            self.title_label = QLabel(title)
            self.title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
            self._layout.addWidget(self.title_label)

    def appearance(self) -> CardAppearance:
        """返回当前填充表面。"""
        return CardAppearance(self.property("appearance"))

    def setAppearance(self, appearance: CardAppearance) -> None:
        """设置填充表面。

        Args:
            appearance: 目标表面。
        """
        if self.appearance() is appearance:
            return
        self.setProperty("appearance", appearance.value)
        self._repolish()

    def isBorderVisible(self) -> bool:
        """返回边框是否可见。"""
        return self.property("border") != "false"

    def setBorderVisible(self, visible: bool) -> None:
        """设置边框显隐。

        Args:
            visible: 是否显示边框。
        """
        if self.isBorderVisible() == visible:
            return
        self.setProperty("border", "true" if visible else "false")
        self._repolish()

    def _repolish(self) -> None:
        """属性变更后触发样式重绘。"""
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        self.update()
