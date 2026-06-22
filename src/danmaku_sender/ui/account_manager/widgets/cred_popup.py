"""凭据弹出框：深色悬浮框，显示完整值 + 复制按钮"""
from PySide6.QtCore import Qt, QTimer
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
            "font-family: Consolas, monospace; font-size: 12px; color: #e0e0e0;"
        )
        layout.addWidget(self._value_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._copy_btn = QPushButton("复制")
        self._copy_btn.setFixedWidth(60)
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
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
                border: 1px solid #333;
                border-radius: 6px;
            }
        """)

    def show_at(self, full_value: str, global_pos):
        self._full_value = full_value
        self._value_label.setText(full_value)
        self._copy_btn.setText("复制")
        self.adjustSize()

        x = global_pos.x()
        y = global_pos.y() - self.height() - 4
        self.move(x, max(0, y))
        self.show()
        self.raise_()
        CredPopup._INSTANCE = self

    def _on_copy(self):
        QApplication.clipboard().setText(self._full_value)
        self._copy_btn.setText("✓")
        self._copy_timer.start(1200)

    @staticmethod
    def close_existing():
        if CredPopup._INSTANCE and CredPopup._INSTANCE.isVisible():
            CredPopup._INSTANCE.close()
            CredPopup._INSTANCE = None

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        QTimer.singleShot(100, self._check_close)

    def _check_close(self):
        if not self.isActiveWindow():
            self.close()
            if CredPopup._INSTANCE is self:
                CredPopup._INSTANCE = None
