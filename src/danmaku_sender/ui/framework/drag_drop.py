"""拖放事件的文件提取与拖放覆盖层"""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .icons import SvgIcon


def xml_files_from_drop(event: QDropEvent) -> list[str]:
    """从拖放事件中提取本地 XML 文件路径。

    Args:
        event: 拖放相关事件，含 QDragEnterEvent 与 QDragMoveEvent。

    Returns:
        list[str]: 命中的 XML 文件路径，顺序与事件给出的一致。
    """
    return [
        url.toLocalFile()
        for url in event.mimeData().urls()
        if url.isLocalFile() and url.toLocalFile().lower().endswith(".xml")
    ]


class DropOverlay(QWidget):
    """拖放进行中覆盖于目标控件的提示层。

    平时隐藏；拖入接受的文件类型时由调用方调用 :meth:`show_overlay` 显示，
    拖离或放下时调用 :meth:`hide` 收起。
    """

    def __init__(self, parent: QWidget, title: str, hint: str) -> None:
        """创建覆盖层并挂载到目标控件。

        Args:
            parent: 被覆盖的目标控件，通常为接受拖放的表格或页面。
            title: 主提示文字，例如「松开以导入文件」。
            hint: 副提示文字，说明支持的文件类型。
        """
        super().__init__(parent)
        self.setObjectName("dropOverlay")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        icon_label = QLabel()
        icon_label.setPixmap(SvgIcon.FILE_OPEN(color="#ffffff").pixmap(48, 48))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("background: transparent;")
        layout.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: white; font-size: 16px; font-weight: bold; background: transparent;")
        layout.addWidget(title_label)

        hint_label = QLabel(hint)
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_label.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 12px; background: transparent;")
        layout.addWidget(hint_label)

        self.setStyleSheet("background-color: rgba(0, 0, 0, 0.4);")
        self.hide()
        parent.installEventFilter(self)

    def show_overlay(self) -> None:
        """铺满目标控件并显示，保证盖在其内容之上。"""
        self._reflow()
        self.show()
        self.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """目标控件尺寸变化、显示时重新定位。

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
        """将自身几何设为父控件大小。"""
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
