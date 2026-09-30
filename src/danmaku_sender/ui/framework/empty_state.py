"""表格空状态引导

数据为空时叠在表格可视区中央的提示块。自己贴住父控件并居中，
调用方只负责决定显隐，不必再写 resizeEvent 与 setGeometry 样板。
"""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_HINT_STYLE = "color: #888; font-size: 14px;"


class EmptyStateHint(QWidget):
    """表格数据为空时的居中引导块。

    纯提示传 ``title`` （可加 ``description``）即可；需要空状态 CTA 时再传
    ``action_text`` / ``secondary_text``，主按钮沿用 ``primary="true"`` 的既有样式。

    监听表格与其可视区的 Resize / Show 自动重定位——首次显示时可视区才有
    尺寸，构造期贴不出正确位置。
    """

    def __init__(
        self,
        view: QAbstractItemView,
        title: str,
        description: str = "",
        action_text: str = "",
        on_action: Callable[[], None] | None = None,
        secondary_text: str = "",
        on_secondary: Callable[[], None] | None = None,
    ) -> None:
        """把引导块贴到表格可视区上。

        Args:
            view: 承载空状态的表格视图，引导块作为其可视区的子控件叠上去。
            title: 主标题，纯提示与 CTA 两种形态都要有。
            description: 副标题，说明缺什么或该做什么；留空则不显示。
            action_text: 主按钮文字；留空则不显示按钮。
            on_action: 主按钮点击回调。
            secondary_text: 次按钮文字；留空则不显示。
            on_secondary: 次按钮点击回调。
        """
        super().__init__(view.viewport())
        self.setObjectName("emptyStateHint")
        self._view = view

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet(_HINT_STYLE)
        layout.addWidget(title_label)

        if description:
            desc_label = QLabel(description)
            desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc_label.setStyleSheet(_HINT_STYLE)
            layout.addWidget(desc_label)

        if action_text or secondary_text:
            buttons = QHBoxLayout()
            buttons.setSpacing(8)
            if action_text:
                buttons.addWidget(self._make_button(action_text, on_action, primary=True))
            if secondary_text:
                buttons.addWidget(self._make_button(secondary_text, on_secondary, primary=False))
            layout.addLayout(buttons)

        self.setVisible(False)
        self.raise_()
        # 两处都装：表格 resize 会带动可视区，但滚动条出没也会单独改可视区尺寸
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)

    @staticmethod
    def _make_button(text: str, on_click: Callable[[], None] | None, primary: bool) -> QPushButton:
        """造一颗空状态按钮。

        Args:
            text: 按钮文字。
            on_click: 点击回调；留空则按钮不接线。
            primary: 是否主操作（走 ``primary="true"`` 的既有样式）。

        Returns:
            QPushButton: 配置好的按钮，由调用方负责布局。
        """
        button = QPushButton(text)
        if primary:
            button.setProperty("primary", "true")
        if on_click is not None:
            button.clicked.connect(on_click)
        return button

    def set_empty(self, empty: bool) -> None:
        """切换空状态显隐；显示时立刻按当前可视区重定位。

        Args:
            empty: 表格是否无数据。
        """
        self.setVisible(empty)
        if empty:
            self._reflow()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """表格或可视区尺寸变化、显示时重定位。

        Args:
            watched: 被监听的控件。
            event: 到达的事件。

        Returns:
            bool: 恒为 False，不拦截事件。
        """
        if watched in (self._view, self.parentWidget()) and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
        ):
            self._reflow()
        return super().eventFilter(watched, event)

    def _reflow(self) -> None:
        """铺满表格可视区，让内部布局把它居中。"""
        self.setGeometry(self._view.viewport().rect())
