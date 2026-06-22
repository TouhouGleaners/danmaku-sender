"""凭据显示行：遮蔽值 + 点击弹出完整值"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..models import _mask
from .cred_popup import CredPopup


class CredLine(QWidget):
    """单个凭据字段的遮蔽显示，点击可弹出完整值"""

    def __init__(self, prefix: str, full_value: str, parent=None):
        super().__init__(parent)
        self._full_value = full_value

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        prefix_label = QLabel(f"{prefix}:")
        prefix_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(prefix_label)

        self._value_label = QLabel(_mask(full_value))
        self._value_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._value_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px; color: #555;"
        )
        self._value_label.mousePressEvent = self._on_click
        layout.addWidget(self._value_label)

        layout.addStretch()

    def _on_click(self, event):
        if CredPopup.is_visible():
            CredPopup.close_popup()
            self._reset_style()
        else:
            CredPopup.show_popup(self._full_value, self._value_label)
            self._value_label.setStyleSheet(
                "font-family: Consolas, monospace; font-size: 11px; color: #2196F3;"
            )

    def _reset_style(self):
        self._value_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px; color: #555;"
        )
