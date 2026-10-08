"""拖放事件的文件提取、拖放覆盖层与拖放过滤器"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QLabel, QVBoxLayout, QWidget

from .icons import SvgIcon


def xml_files_from_drop(event: QDropEvent) -> list[Path]:
    """从拖放事件中提取本地 XML 文件路径。

    Args:
        event: 拖放相关事件，含 QDragEnterEvent 与 QDragMoveEvent。

    Returns:
        list[Path]: 命中的 XML 文件路径，顺序与事件给出的一致。
    """
    return [
        Path(url.toLocalFile())
        for url in event.mimeData().urls()
        if url.isLocalFile() and url.toLocalFile().lower().endswith(".xml")
    ]


class DropOverlay(QWidget):
    """拖放进行中覆盖于目标控件的提示层。

    平时隐藏；拖入接受的文件类型时由调用方调用 :meth:`show_overlay` 显示，
    拖离或放下时调用 :meth:`hide` 收起。

    外观一律由 ``style.qss`` 提供，本类只决定 ``theme`` 动态属性。
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

        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("dropOverlayTitle")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title_label)

        self._hint_label = QLabel(hint)
        self._hint_label.setObjectName("dropOverlayHint")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._hint_label)

        # QWidget 子类不绘制 QSS 背景，需显式声明
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 覆盖层只有文字，不接收输入；否则遮罩一出现，落点就从承载控件移到遮罩自身，承载控件收到 DragLeave，遮罩随之收起
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()
        parent.installEventFilter(self)

    def set_message(self, title: str, hint: str) -> None:
        """改写提示文案，供拖拽过程中按落点切换说法。

        Args:
            title: 主提示文字。
            hint: 副提示文字。
        """
        self._title_label.setText(title)
        self._hint_label.setText(hint)

    def show_overlay(self) -> None:
        """铺满目标控件并显示，保证盖在其内容之上。

        幂等：DragMove 会反复触发本方法，已显示时直接返回。
        """
        if self.isVisible():
            return

        self._apply_theme()
        self._reflow()
        self.show()
        self.raise_()

    def _apply_theme(self) -> None:
        """按当前主题设定 ``theme`` 动态属性，并按前景色重绘图标。

        主题与前景色均取自被覆盖的父控件：本控件的 QSS 会改写自身调色板，
        一律不从自身读取。
        """
        parent = self.parentWidget()
        source = parent if parent is not None else self
        is_dark = source.palette().color(source.backgroundRole()).lightness() < 128

        self.setProperty("theme", "dark" if is_dark else "light")
        self.style().unpolish(self)
        self.style().polish(self)

        self._icon_label.setPixmap(
            SvgIcon.FILE_OPEN(color=source.palette().color(source.foregroundRole()).name()).pixmap(48, 48)
        )

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


class XmlDropFilter(QObject):
    """拦截拖放：只接受恰好一个 XML，拖动中显示遮罩，松手时回调。"""

    def __init__(
        self,
        view: QAbstractItemView,
        overlay: DropOverlay,
        on_drop: Callable[[Path], None],
    ) -> None:
        """挂到目标视图上并开始拦截，随视图一并销毁。

        Args:
            view: 接受拖放的视图。
            overlay: 拖动期间显示的遮罩。
            on_drop: 松手命中 XML 时的回调。
        """
        super().__init__(view)
        self._overlay = overlay
        self._on_drop = on_drop
        self._accepted_path: Path | None = None

        view.setAcceptDrops(True)
        view.viewport().setAcceptDrops(True)
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """拦截视图的拖放事件。

        Args:
            watched (QObject): 被监听的控件。
            event (QEvent): 到达的事件。

        Returns:
            bool: 命中并处理的事件返回 True，其余交回 Qt。
        """
        event_type = event.type()

        if event_type == QEvent.Type.DragLeave:
            return self._handle_drag_leave()

        # 拖放事件 Enter / Move / Drop 均派生自 QDropEvent，一次判断即可收窄
        if isinstance(event, QDropEvent):
            if event_type == QEvent.Type.DragEnter:
                return self._handle_drag_enter(event)
            if event_type == QEvent.Type.DragMove:
                return self._handle_drag_move(event)
            if event_type == QEvent.Type.Drop:
                return self._handle_drop(event)

        return super().eventFilter(watched, event)

    def _handle_drag_enter(self, event: QDropEvent) -> bool:
        """拖入控件时校验文件并建立缓存。

        Args:
            event (QDropEvent): 拖入事件。

        Returns:
            bool: 恒为 True，本次事件已定夺（接受或拒绝）。
        """
        self._accepted_path = self.single_xml(event)

        if self._accepted_path is not None:
            event.acceptProposedAction()
            self._overlay.show_overlay()
        else:
            event.ignore()
            self._overlay.hide()
        return True

    def _handle_drag_move(self, event: QDropEvent) -> bool:
        """拖动过程中复用 Enter 时的校验结果。

        Args:
            event (QDropEvent): 拖动事件。

        Returns:
            bool: 恒为 True，本次事件已定夺。
        """
        if self._accepted_path is not None:
            event.acceptProposedAction()
        else:
            event.ignore()
        return True

    def _handle_drag_leave(self) -> bool:
        """离开控件区域，清理缓存。

        Returns:
            bool: 恒为 False，不拦截事件传递。
        """
        self._accepted_path = None
        self._overlay.hide()
        return False

    def _handle_drop(self, event: QDropEvent) -> bool:
        """松手放置文件。

        Args:
            event (QDropEvent): 放置事件。

        Returns:
            bool: 命中并导入返回 True，否则 False。
        """
        path = self._accepted_path if self._accepted_path is not None else self.single_xml(event)
        self._accepted_path = None
        self._overlay.hide()

        if path is not None:
            event.acceptProposedAction()
            self._on_drop(path)
            return True

        event.ignore()
        return False

    @staticmethod
    def single_xml(event: QDropEvent) -> Path | None:
        """解析拖放事件中的有效 XML 路径。

        Args:
            event (QDropEvent): 拖放相关事件。

        Returns:
            Path | None: 命中的 XML 路径；数量不为一时为 None。
        """
        files = xml_files_from_drop(event)
        return files[0] if len(files) == 1 else None
