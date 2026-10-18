"""Fluent 风格的设置项行：图标、名称、说明与尾部控件。

设置行本身就是一张卡片（继承 :class:`Card`），栅格内边距即卡片的内容边距，不再嵌套第二层容器。
排布对齐 WinUI 的设置行：
图标垂直居中于左侧，名称与说明夹在上下留白之间整体居中，尾部控件靠右。
宽度不足时尾部控件换行到文字下方。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from danmaku_sender.ui.framework.card import Card

ROW_HEIGHT = 74
ROW_HEIGHT_STACKED = 120
STACKED_THRESHOLD = 420
ICON_BOX = 30
ICON_SIZE = 20


class SettingsRow(Card):
    """一行设置项，本身即卡片。

    Attributes:
        icon_label (QWidget | None): 图标控件；未提供图标时为 ``None``。
        title_label (QLabel): 名称控件。
        subtitle_label (QLabel): 说明控件。
    """

    def __init__(
        self,
        title: str,
        subtitle: str,
        trailing: QWidget | None = None,
        icon: QWidget | None = None,
        parent: QWidget | None = None,
    ):
        """初始化设置行。

        Args:
            title (str): 名称文本。
            subtitle (str): 说明文本，超长自动换行。
            trailing (QWidget | None): 尾部控件，如开关或下拉框。
            icon (QWidget | None): 图标控件；省略则不显示图标列。
            parent (QWidget | None): 父控件。
        """
        super().__init__(parent=parent)
        self.setFixedHeight(ROW_HEIGHT)

        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(20, 8, 20, 8)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(6)
        self._grid.setColumnStretch(1, 1)

        self.icon_label = icon
        if icon is not None:
            icon.setFixedSize(ICON_BOX, ICON_BOX)
            self._grid.addWidget(icon, 0, 0, Qt.AlignmentFlag.AlignVCenter)

        text_column = QWidget(self)
        text_layout = QVBoxLayout(text_column)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)

        self.title_label = QLabel(title, text_column)
        self.title_label.setObjectName("settingsRowTitle")

        self.subtitle_label = QLabel(subtitle, text_column)
        self.subtitle_label.setObjectName("settingsRowSubtitle")
        self.subtitle_label.setWordWrap(True)

        # 上下留白把名称与说明夹在中间，整体垂直居中
        text_layout.addStretch(1)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)
        text_layout.addStretch(1)

        self._grid.addWidget(text_column, 0, 1)

        self._trailing = trailing
        self._stacked = False
        if trailing is not None:
            trailing.setAccessibleName(title)
            trailing.setAccessibleDescription(subtitle)
            self._place_trailing()

    def _place_trailing(self) -> None:
        """按当前宽度摆放尾部控件：宽则靠右，窄则换行到文字下方。"""
        if self._trailing is None:
            return
        self._grid.removeWidget(self._trailing)
        self._trailing.setParent(self)
        if self._stacked:
            # 跨满整行，不与文字同列，避免尾部控件被文字列挤窄后溢出
            self._grid.addWidget(self._trailing, 1, 0, 1, -1, Qt.AlignmentFlag.AlignVCenter)
            self.setFixedHeight(ROW_HEIGHT_STACKED)
        else:
            self._grid.addWidget(
                self._trailing, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.setFixedHeight(ROW_HEIGHT)
        self._trailing.show()

    def resizeEvent(self, event) -> None:
        """窗口变窄时把尾部控件换行到文字下方。"""
        stacked = self.width() > 0 and self.width() < STACKED_THRESHOLD
        if stacked != self._stacked:
            self._stacked = stacked
            self._place_trailing()
        super().resizeEvent(event)
