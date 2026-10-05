"""应用内通知卡片

右下角堆叠的轻量提示。发送入口是 :class:`Notification` 的类方法，
宿主由 :meth:`Notification.install` 装上。卡片底部的倒计时条走完自动收起；
悬停时暂停计时，点击卡片或关闭按钮立即收起。
"""

import logging
from enum import Enum
from typing import ClassVar

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QEnterEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import SvgIcon

logger = logging.getLogger(__name__)


def _allow_edge_wrap(text: str, chunk: int = 8) -> str:
    """每 chunk 个字符插入一个零宽空格，给换行提供断点。

    QLabel 的自动换行只在词边界断，长串无断点的文本会整段超宽被裁；
    中文本可逐字断，此处对它无副作用。
    """
    return "​".join(text[i:i + chunk] for i in range(0, len(text), chunk))


class _Level(Enum):
    """通知级别，决定图标与配色。"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    def icon(self):
        """该级别对应的图标。"""
        return {
            _Level.INFO: SvgIcon.INFO,
            _Level.WARNING: SvgIcon.WARNING,
            _Level.ERROR: SvgIcon.ERROR,
        }[self]

    def color(self) -> str:
        """该级别的十六进制配色。"""
        return {
            _Level.INFO: "#3498db",
            _Level.WARNING: "#f39c12",
            _Level.ERROR: "#e74c3c",
        }[self]


class Notification:
    """右下角通知卡片的发送入口。"""

    DEFAULT_TIMEOUT_MS = 5000

    _host: ClassVar["NotificationHost | None"] = None

    @classmethod
    def install(cls, parent: QWidget) -> "NotificationHost":
        """在父控件右下角装上通知宿主。

        Args:
            parent: 承载通知堆的窗口或大控件。

        Returns:
            NotificationHost: 装好的宿主。
        """
        cls._host = NotificationHost(parent)
        return cls._host

    @classmethod
    def info(cls, title: str, message: str, timeout_ms: int | None = None) -> None:
        """弹出一条提示。

        Args:
            title: 标题。
            message: 正文。
            timeout_ms: 自动收起的时长；<= 0 表示不自动收起。
        """
        cls._push(_Level.INFO, title, message, cls.DEFAULT_TIMEOUT_MS if timeout_ms is None else timeout_ms)

    @classmethod
    def warning(cls, title: str, message: str, timeout_ms: int | None = None) -> None:
        """弹出一条警告。

        Args:
            title: 标题。
            message: 正文。
            timeout_ms: 自动收起的时长；<= 0 表示不自动收起。
        """
        cls._push(_Level.WARNING, title, message, cls.DEFAULT_TIMEOUT_MS if timeout_ms is None else timeout_ms)

    @classmethod
    def error(cls, title: str, message: str, timeout_ms: int | None = None) -> None:
        """弹出一条错误。

        Args:
            title: 标题。
            message: 正文。
            timeout_ms: 自动收起的时长；<= 0 表示不自动收起。
        """
        cls._push(_Level.ERROR, title, message, cls.DEFAULT_TIMEOUT_MS if timeout_ms is None else timeout_ms)

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
        self._color = QColor(level.color())
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
        painter.setBrush(self._color)
        radius = min(self.height() / 2, width / 2)
        path = QPainterPath()
        path.addRoundedRect(0, 0, width, self.height(), radius, radius)
        painter.drawPath(path)


class _NotificationCard(QFrame):
    """一张通知卡片。

    Args:
        level: 级别，决定图标与配色。
        title: 标题。
        message: 正文。
        timeout_ms: 自动收起的时长；<= 0 表示不自动收起。
    """

    WIDTH = 360
    BODY_MARGIN_LEFT = 12
    BODY_MARGIN_RIGHT = 8
    BODY_SPACING = 8
    ICON = 16
    CLOSE = 20
    ENTER_MS = 180
    EXIT_MS = 150
    ENTER_SLIDE_PX = 12

    closed = Signal()

    def __init__(
        self,
        level: _Level,
        title: str,
        message: str,
        timeout_ms: int,
    ) -> None:
        super().__init__()
        self.setObjectName("notificationCard")
        self._level = level
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedWidth(self.WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QWidget()
        body.setObjectName("notificationBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(self.BODY_MARGIN_LEFT, 6, self.BODY_MARGIN_RIGHT, 6)
        body_layout.setSpacing(self.BODY_SPACING)

        icon_label = QLabel()
        icon_label.setPixmap(level.icon()(color=level.color()).pixmap(self.ICON, self.ICON))
        body_layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        texts = QVBoxLayout()
        texts.setSpacing(0)

        self._title_text = title
        self._title = QLabel(title)
        self._title.setObjectName("notificationTitle")
        self._title.setWordWrap(False)
        self._title.setMinimumWidth(0)
        self._title.setToolTip(title)
        self._title.ensurePolished()
        title_metrics = self._title.fontMetrics()
        self._title.setFixedHeight(title_metrics.ascent() + title_metrics.descent())
        texts.addWidget(self._title)

        self._message_text = message
        self._label = QLabel(_allow_edge_wrap(message))
        self._label.setObjectName("notificationMessage")
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(True)
        self._label.setMinimumWidth(0)
        self._label.setToolTip(message)
        texts.addWidget(self._label)

        close_btn = QToolButton()
        close_btn.setObjectName("notificationClose")
        close_btn.setIcon(SvgIcon.CLOSE)
        close_btn.setIconSize(QSize(self.ICON, self.ICON))
        close_btn.setAutoRaise(True)
        close_btn.setFixedSize(self.CLOSE, self.CLOSE)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.dismiss)

        body_layout.addLayout(texts, stretch=1)
        body_layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addWidget(body)

        self._countdown = _CountdownBar(level)
        layout.addWidget(self._countdown)

        self.setFixedHeight(self.sizeHint().height())

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)
        self._exiting = False
        self._enter_animation: QPropertyAnimation | None = None

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

        self._fit_text()

    @property
    def level(self) -> str:
        """卡片级别，取值 info / warning / error。"""
        return self._level.value

    @property
    def title(self) -> str:
        """卡片标题"""
        return self._title_text

    @property
    def message(self) -> str:
        """卡片正文"""
        return self._label.text()

    def resizeEvent(self, event) -> None:
        """尺寸变化后重排标题与正文。"""
        super().resizeEvent(event)
        self._fit_text()

    def _fit_text(self) -> None:
        """按可用宽度给标题加省略号，按正文的实际行数裁高，并跟随调整卡片高度。"""
        title_width = self._title.width()
        if title_width > 0:
            title_metrics = self._title.fontMetrics()
            self._title.setText(
                title_metrics.elidedText(self._title_text, Qt.TextElideMode.ElideRight, title_width)
            )

        message_width = (
            self.WIDTH
            - 2  # 卡片边框
            - self.BODY_MARGIN_LEFT
            - self.BODY_MARGIN_RIGHT
            - self.ICON
            - self.CLOSE
            - 2 * self.BODY_SPACING
        )
        metrics = self._label.fontMetrics()
        line_height = metrics.ascent() + metrics.descent()
        wrapped = metrics.boundingRect(
            QRect(0, 0, message_width, 1 << 30),
            Qt.TextFlag.TextWordWrap,
            self._label.text(),
        )
        lines = max(1, round(wrapped.height() / metrics.height()))
        self._label.setFixedHeight(line_height * lines)
        target = self.sizeHint().height()
        if self.height() != target:
            self.setFixedHeight(target)

    def play_enter(self, target_pos: QPoint) -> None:
        """自底部滑入并淡入到指定位置。

        Args:
            target_pos: 卡片在宿主内的最终坐标。
        """
        self.move(target_pos + QPoint(0, self.ENTER_SLIDE_PX))
        self._opacity.setOpacity(0.0)

        slide = QPropertyAnimation(self, b"pos", self)
        slide.setStartValue(target_pos + QPoint(0, self.ENTER_SLIDE_PX))
        slide.setEndValue(target_pos)
        slide.setDuration(self.ENTER_MS)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._enter_animation = slide
        slide.finished.connect(self._clear_enter_animation)
        slide.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        fade = QPropertyAnimation(self._opacity, b"opacity", self)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setDuration(self.ENTER_MS)
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _clear_enter_animation(self) -> None:
        self._enter_animation = None

    def snap_to(self, pos: QPoint) -> None:
        """直接落到指定位置，中止进行中的入场动画。

        Args:
            pos: 卡片在宿主内的坐标。
        """
        if self._enter_animation is not None:
            self._enter_animation.stop()
            self._enter_animation = None
        self.move(pos)

    def dismiss(self) -> None:
        """淡出后从卡片堆移除。"""
        if self._exiting:
            return
        self._exiting = True
        self._animation.stop()

        fade = QPropertyAnimation(self._opacity, b"opacity", self)
        fade.setStartValue(self._opacity.opacity())
        fade.setEndValue(0.0)
        fade.setDuration(self.EXIT_MS)
        fade.finished.connect(self.closed.emit)
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

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

    自身尺寸只覆盖卡片堆，不遮挡窗口其余部分；
    跟随父控件尺寸变化重新定位。最新的卡片排在堆底。
    """

    MARGIN = 12
    ACTION_BAR_CLEARANCE = 40
    SPACING = 8
    MAX_CARDS = 5

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("notificationHost")
        self._cards: list[_NotificationCard] = []

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
        timeout_ms: int,
    ) -> None:
        """在右下角追加一张通知卡片。"""
        card = _NotificationCard(level, title, message, timeout_ms)
        card.closed.connect(lambda c=card: self._remove(c))
        card.setParent(self)
        card.show()  # 换父后控件处于隐藏态
        self._cards.append(card)
        self._trim()
        self.show()
        self.raise_()
        self._relayout()
        card.play_enter(self._card_pos(card))

    def _trim(self) -> None:
        """丢弃最旧的卡片，保证堆高不超过 MAX_CARDS。"""
        while len(self._cards) > self.MAX_CARDS:
            oldest = self._cards.pop(0)
            oldest.deleteLater()

    def _remove(self, card: _NotificationCard) -> None:
        if card not in self._cards:
            return

        self._cards.remove(card)
        card.deleteLater()
        self._relayout()

    def _card_pos(self, card: _NotificationCard) -> QPoint:
        """卡片在宿主内的目标坐标，先加入的在上。"""
        y = 0
        for c in self._cards:
            if c is card:
                break
            y += c.height() + self.SPACING
        return QPoint(0, y)

    def _relayout(self) -> None:
        """摆好卡片并把宿主贴到父控件右下角、页面操作栏之上。"""
        if not self._cards:
            self.hide()
            return
        self._trim_to_fit()
        y = 0
        for card in self._cards:
            card.snap_to(QPoint(0, y))
            y += card.height() + self.SPACING
        self._reflow()

    def _trim_to_fit(self) -> None:
        """丢弃最旧的卡片，直到整堆能装进父控件的可用高度。"""
        parent = self.parentWidget()
        if parent is None:
            return
        max_height = parent.height() - self.ACTION_BAR_CLEARANCE - 2 * self.MARGIN
        while len(self._cards) > 1:
            stack = sum(c.height() for c in self._cards) + self.SPACING * (len(self._cards) - 1)
            if stack <= max_height:
                break
            oldest = self._cards.pop(0)
            oldest.deleteLater()

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

        height = sum(c.height() for c in self._cards)
        height += self.SPACING * (len(self._cards) - 1)
        max_height = parent.height() - self.ACTION_BAR_CLEARANCE - 2 * self.MARGIN
        height = min(height, max(0, max_height))
        self.setGeometry(
            parent.width() - _NotificationCard.WIDTH - self.MARGIN,
            parent.height() - height - self.ACTION_BAR_CLEARANCE - self.MARGIN,
            _NotificationCard.WIDTH,
            height,
        )
