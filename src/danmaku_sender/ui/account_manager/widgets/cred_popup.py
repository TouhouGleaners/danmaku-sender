"""凭据弹出框：深色悬浮框，显示完整值 + 复制按钮"""
from PySide6.QtCore import Qt, QTimer, QEvent, QObject
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QApplication


class CredPopup(QWidget):
    """独立顶层窗口，显示完整凭据值"""

    _INSTANCE: 'CredPopup | None' = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self._value_label = QLabel()
        self._value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._value_label.setWordWrap(True)
        self._value_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 12px; color: #e0e0e0; "
            "background: transparent;"
        )
        layout.addWidget(self._value_label)

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
        layout.addLayout(btn_row)

        self._full_value = ""
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(lambda: self._copy_btn.setText("复制"))

        self.setStyleSheet("""
            CredPopup {
                background: #1e1e1e;
                border: 1px solid #444;
                border-radius: 6px;
            }
        """)

        # 监听全局鼠标点击，点击弹窗外任意位置关闭
        QApplication.instance().installEventFilter(self)

    def show_at(self, full_value: str, anchor_widget: QWidget):
        """在指定控件正上方显示"""
        self._full_value = full_value
        self._value_label.setText(full_value)
        self._copy_btn.setText("复制")
        self.adjustSize()

        # 定位到 anchor 正上方
        anchor_global = anchor_widget.mapToGlobal(anchor_widget.rect().topLeft())
        x = anchor_global.x()
        y = anchor_global.y() - self.height() - 4
        self.move(x, max(0, y))
        self.show()
        self.raise_()

        CredPopup._INSTANCE = self

    def _on_copy(self):
        QApplication.clipboard().setText(self._full_value)
        self._copy_btn.setText("✓")
        self._copy_timer.start(1200)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """全局鼠标点击：点击弹窗外关闭"""
        if event.type() == QEvent.Type.MouseButtonPress:
            if self.isVisible() and not self.underMouse():
                self.close()
                if CredPopup._INSTANCE is self:
                    CredPopup._INSTANCE = None
        return super().eventFilter(obj, event)

    @staticmethod
    def close_existing():
        if CredPopup._INSTANCE and CredPopup._INSTANCE.isVisible():
            CredPopup._INSTANCE.close()
            CredPopup._INSTANCE = None

    def closeEvent(self, event):
        # 移除全局事件过滤器
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)
