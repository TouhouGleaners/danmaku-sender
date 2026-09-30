"""表格空状态引导

数据为空时覆盖于表格可视区中央的提示块。组件自行对齐父控件可视区并居中，
调用方仅需控制显隐，无需重复实现 resizeEvent 与 setGeometry。
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

    仅需提示时传入 ``title`` （可选 ``description``）；
    需要空状态 CTA 时再传``action_text`` / ``secondary_text``，主按钮沿用 ``primary="true"`` 的既有样式。

    组件监听表格及其可视区的 Resize / Show 事件并自动重定位——首次显示时
    可视区才有确定尺寸，构造阶段无法取得正确位置。
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
        """创建引导块并挂载到表格可视区。

        Args:
            view: 承载空状态的表格视图，引导块作为其可视区的子控件叠加显示。
            title: 主标题，纯提示与 CTA 两种形态均需提供。
            description: 副标题，用于说明缺失内容或后续操作；留空则不显示。
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
        # 表格与可视区两处都需监听：表格尺寸变化会带动可视区，
        # 滚动条的出现与消失也会单独改变可视区尺寸
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)

    @staticmethod
    def _make_button(text: str, on_click: Callable[[], None] | None, primary: bool) -> QPushButton:
        """创建空状态按钮。

        Args:
            text: 按钮文字。
            on_click: 点击回调；留空则不连接信号。
            primary: 是否为主操作，为真时挂 ``primary="true"`` 复用既有样式。

        Returns:
            QPushButton: 配置完成的按钮，由调用方负责布局。
        """
        button = QPushButton(text)
        if primary:
            button.setProperty("primary", "true")
        if on_click is not None:
            button.clicked.connect(on_click)
        return button

    def set_empty(self, empty: bool) -> None:
        """切换空状态显隐；显示时立即按当前可视区重新定位。

        Args:
            empty: 表格是否无数据。
        """
        self.setVisible(empty)
        if empty:
            self._reflow()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """表格或可视区尺寸变化、显示时重新定位。

        Args:
            watched: 被监听的控件。
            event: 到达的事件。

        Returns:
            bool: 恒为 False，不拦截事件传递。
        """
        if watched in (self._view, self.parentWidget()) and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
        ):
            self._reflow()
        return super().eventFilter(watched, event)

    def _reflow(self) -> None:
        """将自身几何设为表格可视区大小，由内部布局完成居中。"""
        self.setGeometry(self._view.viewport().rect())
