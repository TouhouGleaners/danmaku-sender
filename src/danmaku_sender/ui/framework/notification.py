"""应用内通知卡片

右下角堆叠的轻量提示。
卡片底部的倒计时条走完自动收起；
悬停时暂停计时并高亮卡片，点击卡片或关闭按钮立即收起。
"""

import logging

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

# 卡片与宿主窗口右、下边缘的间距
MARGIN = 16
# 通知底部要让开页面操作栏（状态行 + 启动/停止按钮）的高度
ACTION_BAR_CLEARANCE = 52
# 卡片固定宽度，不随文案长短变化
CARD_WIDTH = 360
# 卡片最小高度，防止堆叠时被压扁
CARD_MIN_HEIGHT = 56
# 同时最多显示的卡片数，超出后丢弃最旧的
MAX_CARDS = 5
# 堆叠时卡片之间的纵向间距
SPACING = 8
# 默认存活时长
DEFAULT_TIMEOUT_MS = 8000


class CountdownBar(QWidget):
    """卡片底部的倒计时条，由 1 平滑递减到 0。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        painter.setBrush(self.palette().highlight())
        radius = min(self.height() / 2, width / 2)
        path = QPainterPath()
        path.addRoundedRect(0, 0, width, self.height(), radius, radius)
        painter.drawPath(path)


class NotificationCard(QFrame):
    """一张通知卡片。

    Args:
        message: 正文。
        timeout_ms: 自动收起的时长；<= 0 表示不自动收起。
    """

    closed = Signal()

    def __init__(self, message: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> None:
        super().__init__()
        self.setObjectName("notificationCard")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMinimumHeight(CARD_MIN_HEIGHT)
        self.setFixedWidth(CARD_WIDTH)
        # 纵向固定：布局不许拉伸卡片，堆高由宿主按卡片数算
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._timeout_ms = timeout_ms

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QWidget()
        body.setObjectName("notificationBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 10, 8, 10)
        body_layout.setSpacing(8)

        self._label = QLabel(message)
        self._label.setObjectName("notificationMessage")
        self._label.setWordWrap(True)
        body_layout.addWidget(self._label, stretch=1)

        close_btn = QPushButton()
        close_btn.setObjectName("notificationClose")
        close_btn.setIcon(SvgIcon.CLOSE)
        close_btn.setFixedSize(20, 20)
        close_btn.setFlat(True)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.dismiss)
        body_layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignTop)

        layout.addWidget(body)
        layout.addStretch()

        self._countdown = CountdownBar()
        self._countdown.setObjectName("notificationCountdown")
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
    def message(self) -> str:
        """卡片正文。"""
        return self._label.text()

    def dismiss(self) -> None:
        """立即收起这张卡片。"""
        self._animation.stop()
        self.closed.emit()

    def enterEvent(self, event: QEnterEvent) -> None:
        """悬停时暂停倒计时。"""
        if self._animation.state() == QPropertyAnimation.State.Running:
            self._animation.pause()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        """离开后若仍有剩余时间，继续倒计时。"""
        if self._animation.state() == QPropertyAnimation.State.Paused:
            self._animation.resume()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """点击卡片任意处收起。"""
        self.dismiss()
        super().mousePressEvent(event)


class NotificationHost(QWidget):
    """右下角堆叠通知卡片的容器。

    自身尺寸只覆盖卡片堆，不遮挡窗口其余部分；跟随父控件尺寸变化重新定位。
    最新的卡片排在堆底。
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("notificationHost")

        self._cards: list[NotificationCard] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(SPACING)
        self._layout.addStretch()

        self.hide()
        parent.installEventFilter(self)

    @property
    def cards(self) -> list[NotificationCard]:
        """当前卡片堆，先加入的在前。"""
        return list(self._cards)

    def notify(self, message: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> None:
        """在右下角追加一张通知卡片。

        Args:
            message: 正文。
            timeout_ms: 自动收起的时长；<= 0 表示不自动收起。
        """
        card = NotificationCard(message, timeout_ms)
        card.closed.connect(lambda c=card: self._remove(c))
        self._cards.append(card)
        self._layout.addWidget(card)
        self._trim()
        self.show()
        self.raise_()
        self._reflow()

    def _trim(self) -> None:
        """丢弃最旧的卡片，保证堆高不超过可用空间。"""
        while len(self._cards) > MAX_CARDS:
            oldest = self._cards[0]
            self._cards.pop(0)
            self._layout.removeWidget(oldest)
            oldest.deleteLater()

    def _remove(self, card: NotificationCard) -> None:
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
        height += SPACING * (len(self._cards) - 1)
        width = CARD_WIDTH
        # 堆高不超可用空间，免得卡片被压扁
        max_height = parent.height() - ACTION_BAR_CLEARANCE - 2 * MARGIN
        height = min(height, max(0, max_height))
        self.setGeometry(
            parent.width() - width - MARGIN,
            parent.height() - height - ACTION_BAR_CLEARANCE - MARGIN,
            width,
            height,
        )


# ── 模块级入口：任意 UI 代码直接 notify(...) ─────────────────

_host: NotificationHost | None = None


def attach(host: NotificationHost) -> None:
    """安装通知宿主；由主窗口在建好界面后调用一次。

    Args:
        host: 承载卡片堆的容器。
    """
    global _host
    _host = host


def notify(message: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> None:
    """在右下角弹出一条通知。

    Args:
        message: 正文。
        timeout_ms: 自动收起的时长；<= 0 表示不自动收起。
    """
    if _host is None:
        logger.warning(f"通知宿主未安装，丢弃通知: {message}")
        return
    _host.notify(message, timeout_ms)
