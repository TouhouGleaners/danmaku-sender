"""凭据弹出框：深色悬浮框，显示完整值 + 复制按钮"""
from PySide6.QtCore import Qt, QTimer, QEvent, QObject
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QApplication


class CredPopup(QWidget):
    """全局单例悬浮框"""

    _INSTANCE: 'CredPopup | None' = None

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setFixedWidth(320)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._container = QWidget()
        self._container.setObjectName("credPopupContainer")
        inner = QVBoxLayout(self._container)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.setSpacing(8)

        self._value_label = QLabel()
        self._value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._value_label.setWordWrap(True)
        self._value_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 12px; color: #e0e0e0;"
        )
        inner.addWidget(self._value_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._copy_btn = QPushButton("复制")
        self._copy_btn.setFixedWidth(60)
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setStyleSheet(
            "QPushButton { background: #333; color: #e0e0e0; border: 1px solid #555; "
            "border-radius: 4px; padding: 4px 8px; } "
            "QPushButton:hover { background: #444; }"
        )
        self._copy_btn.clicked.connect(self._on_copy)
        btn_row.addWidget(self._copy_btn)
        inner.addLayout(btn_row)

        outer.addWidget(self._container)

        self._full_value = ""
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(lambda: self._copy_btn.setText("复制"))

        self._container.setStyleSheet(
            "QWidget#credPopupContainer { background: #1e1e1e; border: 1px solid #444; border-radius: 6px; }"
        )

        # 安装全局事件过滤器：鼠标点击弹窗外时关闭
        QApplication.instance().installEventFilter(self)

    @staticmethod
    def show_popup(full_value: str, anchor_widget: QWidget):
        if CredPopup._INSTANCE is None:
            CredPopup._INSTANCE = CredPopup()

        popup = CredPopup._INSTANCE
        popup._full_value = full_value
        popup._value_label.setText(full_value)
        popup._copy_btn.setText("复制")
        popup.adjustSize()

        global_top_left = anchor_widget.mapToGlobal(anchor_widget.rect().topLeft())
        x = global_top_left.x()
        y = global_top_left.y() - popup.height() - 4
        popup.move(x, max(0, y))
        popup.show()
        popup.raise_()

    @staticmethod
    def close_popup():
        if CredPopup._INSTANCE and CredPopup._INSTANCE.isVisible():
            CredPopup._INSTANCE.hide()

    @staticmethod
    def is_visible() -> bool:
        return CredPopup._INSTANCE is not None and CredPopup._INSTANCE.isVisible()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """鼠标点击弹窗外时关闭"""
        if event.type() == QEvent.Type.MouseButtonPress and self.isVisible():
            # 判断点击是否在弹窗内部
            global_pos = event.globalPosition().toPoint()
            if not self.geometry().contains(global_pos):
                self.hide()
        return super().eventFilter(obj, event)

    def _on_copy(self):
        QApplication.clipboard().setText(self._full_value)
        self._copy_btn.setText("✓")
        self._copy_timer.start(1200)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)
