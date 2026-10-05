"""应用内通知卡片

右下角堆叠的轻量提示。
发送入口是 :class:`Notification` 的类方法；
宿主由主窗口 :func:`install` 一次，之后任意 UI 代码即可发送。
卡片底部的倒计时条走完自动收起；
悬停时暂停计时并高亮卡片，点击卡片或关闭按钮立即收起。
"""

import logging
from enum import Enum
from typing import ClassVar

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    Qt,
    Signal,
)
from PySide6.QtGui import QEnterEvent, QMouseEvent, QPainter, QPainterPath, QPaintEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .icons import SvgIcon

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 5000


class _Level(Enum):
    """通知级别，决定卡片左侧色条与倒计时条的配色。"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Notification:
    """右下角通知卡片的发送入口。

    主窗口 :meth:`install` 一次，之后任意 UI 代码用 :meth:`info` /
    :meth:`warning` / :meth:`error` 发送。
    """

    _host: ClassVar["NotificationHost | None"] = None

    @classmethod
    def install(cls, parent: QWidget) -> "NotificationHost":
        """在父控件右下角装上通知宿主；主窗口建好界面后调用一次。

        Args:
            parent: 承载通知堆的窗口或大控件。

        Returns:
            NotificationHost: 装好的宿主。
        """
        cls._host = NotificationHost(parent)
        return cls._host

    @classmethod
    def info(cls, title: str, message: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> None:
        """弹出一条提示。

        Args:
            title: 标题。
            message: 正文。
            timeout_ms: 自动收起的时长；<= 0 表示不自动收起。
        """
        cls._push(_Level.INFO, title, message, timeout_ms)

    @classmethod
    def warning(cls, title: str, message: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> None:
        """弹出一条警告。

        Args:
            title: 标题。
            message: 正文。
            timeout_ms: 自动收起的时长；<= 0 表示不自动收起。
        """
        cls._push(_Level.WARNING, title, message, timeout_ms)

    @classmethod
    def error(cls, title: str, message: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> None:
        """弹出一条错误。

        Args:
            title: 标题。
            message: 正文。
            timeout_ms: 自动收起的时长；<= 0 表示不自动收起。
        """
        cls._push(_Level.ERROR, title, message, timeout_ms)

    @classmethod
    def _push(cls, level: _Level, title: str, message: str, timeout_ms: int) -> None:
        if cls._host is None:
            logger.warning(f"通知宿主未安装，丢弃通知: {title} — {message}")
            return
        cls._host.push(level, title, message, timeout_ms)


class _CountdownBar(QWidget):
    """卡片底部的倒计时条，由 1 平滑递减到 0。"""

    def __init__(self, level: _Level, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("notificationCountdown")
        self.setProperty("level", level.value)
        self._progress = 1.0
        self.setFixedHeight(3)

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, value))
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def paintEvent(self, event: QPaintEvent) -> None:
        width = self.width() * self._progress
        if width <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().color(self.foregroundRole()))
        radius = min(self.height() / 2, width / 2)
        path = QPainterPath()
        path.addRoundedRect(0, 0, width, self.height(), radius, radius)
        painter.drawPath(path)


class _NotificationCard(QFrame):
    """一张通知卡片。

    Args:
        level: 级别，决定配色。
        title: 标题。
        message: 正文。
        timeout_ms: 自动收起的时长；<= 0 表示不自动收起。
    """

    WIDTH = 360
    MIN_HEIGHT = 56

    closed = Signal()

    def __init__(
        self,
        level: _Level,
        title: str,
        message: str,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        super().__init__()
        self.setObjectName("notificationCard")
        self.setProperty("level", level.value)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMinimumHeight(self.MIN_HEIGHT)
        self.setFixedWidth(self.WIDTH)
        # 纵向固定：布局不许拉伸卡片，堆高由宿主按卡片数算
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QWidget()
        body.setObjectName("notificationBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(10, 10, 8, 10)
        body_layout.setSpacing(8)

        accent = QFrame()
        accent.setObjectName("notificationAccent")
        accent.setProperty("level", level.value)
        accent.setFixedWidth(3)
        body_layout.addWidget(accent)

        texts = QVBoxLayout()
        texts.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._title = QLabel(title)
        self._title.setObjectName("notificationTitle")
        title_row.addWidget(self._title, stretch=1)

        close_btn = QPushButton()
        close_btn.setObjectName("notificationClose")
        close_btn.setIcon(SvgIcon.CLOSE)
        close_btn.setFixedSize(20, 20)
        close_btn.setFlat(True)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.dismiss)
        title_row.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignTop)

        texts.addLayout(title_row)

        self._label = QLabel(message)
        self._label.setObjectName("notificationMessage")
        self._label.setWordWrap(True)
        texts.addWidget(self._label)

        body_layout.addLayout(texts, stretch=1)
        layout.addWidget(body)

        self._countdown = _CountdownBar(level)
        layout.addWidget(self._countdown)

        self._animation = QPropertyAnimation(self._countdown, b"progress", self)
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.0)
        self._animation.setDuration(timeout_ms if timeout_ms > 0 else 1)
        self._animation.setEasingCurve(QEasingCurve.Type.Linear)
        self._animation.finished.connect(self.dismiss)
        if timeout_ms > 0:
            self._animation.start()
        else:
            self._countdown.hide()

    @property
    def title(self) -> str:
        """卡片标题"""
        return self._title.text()

    @property
    def message(self) -> str:
        """卡片正文"""
        return self._label.text()

    def dismiss(self) -> None:
        """立即收起这张卡片"""
        self._animation.stop()
        self.closed.emit()

    def enterEvent(self, event: QEnterEvent) -> None:
        """悬停时暂停倒计时"""
        if self._animation.state() == QPropertyAnimation.State.Running:
            self._animation.pause()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        """离开后若仍有剩余时间，继续倒计时"""
        if self._animation.state() == QPropertyAnimation.State.Paused:
            self._animation.resume()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """点击卡片任意处收起"""
        self.dismiss()
        super().mousePressEvent(event)


class NotificationHost(QWidget):
    """右下角堆叠通知卡片的容器。

    自身尺寸只覆盖卡片堆，不遮挡窗口其余部分；跟随父控件尺寸变化重新定位。
    最新的卡片排在堆底。
    """

    MARGIN = 16
    ACTION_BAR_CLEARANCE = 52
    SPACING = 8
    MAX_CARDS = 5

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("notificationHost")

        self._cards: list[_NotificationCard] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(self.SPACING)
        self._layout.addStretch()

        self.hide()
        parent.installEventFilter(self)

    @property
    def cards(self) -> list[_NotificationCard]:
        """当前卡片堆，先加入的在前。"""
        return list(self._cards)

    def push(
        self,
        level: _Level,
        title: str,
        message: str,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        """在右下角追加一张通知卡片。"""
        card = _NotificationCard(level, title, message, timeout_ms)
        card.closed.connect(lambda c=card: self._remove(c))
        self._cards.append(card)
        self._layout.addWidget(card)
        self._trim()
        self.show()
        self.raise_()
        self._reflow()

    def _trim(self) -> None:
        """丢弃最旧的卡片，保证堆高不超过可用空间。"""
        while len(self._cards) > self.MAX_CARDS:
            oldest = self._cards[0]
            self._cards.pop(0)
            self._layout.removeWidget(oldest)
            oldest.deleteLater()

    def _remove(self, card: _NotificationCard) -> None:
        if card not in self._cards:
            return
        self._cards.remove(card)
        self._layout.removeWidget(card)
        card.deleteLater()
        if not self._cards:
            self.hide()
            return
        self._reflow()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """父控件尺寸变化时重新定位。

        Args:
            watched: 被监听的控件。
            event: 到达的事件。

        Returns:
            bool: 恒为 False，不拦截事件传递。
        """
        if watched is self.parentWidget() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._reflow()
        return super().eventFilter(watched, event)

    def _reflow(self) -> None:
        """贴到父控件右下角、页面操作栏之上，尺寸只覆盖卡片堆。"""
        parent = self.parentWidget()
        if parent is None or not self.isVisible() or not self._cards:
            return

        # 逐张累加而不是读 sizeHint：addWidget 后布局尚未重算，sizeHint 是旧值
        height = sum(max(c.minimumHeight(), c.sizeHint().height()) for c in self._cards)
        height += self.SPACING * (len(self._cards) - 1)

        # 堆高不超可用空间，免得卡片被压扁
        max_height = parent.height() - self.ACTION_BAR_CLEARANCE - 2 * self.MARGIN
        height = min(height, max(0, max_height))
        self.setGeometry(
            parent.width() - _NotificationCard.WIDTH - self.MARGIN,
            parent.height() - height - self.ACTION_BAR_CLEARANCE - self.MARGIN,
            _NotificationCard.WIDTH,
            height,
        )
