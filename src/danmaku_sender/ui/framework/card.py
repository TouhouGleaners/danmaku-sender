"""Fluent 风格卡片容器。

非交互式表面，用于分组呈现调用方的内容。
外观由 ``style.qss`` 的``QFrame#card`` 规则绘制，本模块负责维护外观属性与悬停底板。
悬停底板在开启后随指针进出渐显渐隐，叠加于样式绘制之上，不覆盖边框。
"""

from enum import Enum

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QEnterEvent, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import QApplication, QFrame, QWidget


class CardAppearance(Enum):
    """卡片的填充表面，对应表面层级。

    层级自底向上为 canvas → layer → layer_alt / overlay。
    """

    CANVAS = "canvas"
    LAYER = "layer"
    LAYER_ALT = "alt"
    OVERLAY = "overlay"


class Card(QFrame):
    """圆角卡片表面，内容与布局由调用方管理。

    本类负责外观属性、样式重绘与悬停底板，不创建布局——调用方或子类自行
    建立布局挂载内容。
    """

    # 悬停底板：内缩一个边框宽度，避免覆盖样式绘制的描边
    PLATE_INSET = 1
    PLATE_RADIUS = 3
    FADE_MS = 150

    def __init__(self, parent: QWidget | None = None):
        """初始化卡片。

        Args:
            parent (QWidget | None): 父控件。
        """
        super().__init__(parent)
        self.setObjectName("card")
        self.setProperty("appearance", CardAppearance.LAYER.value)
        self.setProperty("border", "true")

        self._hoverable = False
        self._plate_reveal = 0.0
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(self.FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.valueChanged.connect(self._accept_reveal)

    def appearance(self) -> CardAppearance:
        """返回当前填充表面。"""
        return CardAppearance(self.property("appearance"))

    def setAppearance(self, appearance: CardAppearance) -> None:
        """设置填充表面。

        Args:
            appearance (CardAppearance): 目标表面。
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
            visible (bool): 是否显示边框。
        """
        if self.isBorderVisible() == visible:
            return
        self.setProperty("border", "true" if visible else "false")
        self._repolish()

    def isHoverable(self) -> bool:
        """返回悬停底板是否开启。"""
        return self._hoverable

    def setHoverable(self, hoverable: bool) -> None:
        """开启或关闭悬停底板。

        Args:
            hoverable (bool): 指针悬停其上时是否渐显底板。
        """
        if self._hoverable == hoverable:
            return
        self._hoverable = hoverable
        if not hoverable:
            self._reveal_to(0.0)

    def enterEvent(self, event: QEnterEvent) -> None:
        """指针进入时渐显底板。"""
        super().enterEvent(event)
        if self._hoverable:
            self._reveal_to(1.0)

    def leaveEvent(self, event: QEvent) -> None:
        """指针离开时渐隐底板。"""
        super().leaveEvent(event)
        self._reveal_to(0.0)

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制样式外观，随后叠加悬停底板。"""
        super().paintEvent(event)
        if self._plate_reveal <= 0.0:
            return

        app = QApplication.instance()
        palette = app.palette() if isinstance(app, QApplication) else self.palette()
        color = QColor(palette.color(QPalette.ColorRole.Button))
        color.setAlphaF(color.alphaF() * self._plate_reveal)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(
            self.rect().adjusted(self.PLATE_INSET, self.PLATE_INSET,
                                 -self.PLATE_INSET, -self.PLATE_INSET),
            self.PLATE_RADIUS,
            self.PLATE_RADIUS,
        )

    def _reveal_to(self, goal: float) -> None:
        """将底板渐显进度推向目标值。

        Args:
            goal (float): 目标进度，取值 0 到 1。
        """
        if abs(self._plate_reveal - goal) < 1e-6:
            return
        if (
            self._fade.state() != QAbstractAnimation.State.Stopped
            and self._fade.endValue() == goal
        ):
            return
        self._fade.stop()
        self._fade.setStartValue(self._plate_reveal)
        self._fade.setEndValue(goal)
        self._fade.start()

    def _accept_reveal(self, value: float) -> None:
        self._plate_reveal = float(value)
        self.update()

    def _repolish(self) -> None:
        """属性变更后触发样式重绘。"""
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        self.update()
