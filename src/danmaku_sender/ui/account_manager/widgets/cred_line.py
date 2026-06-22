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
        self._popup: CredPopup | None = None
        self._is_showing = False

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
        if self._is_showing:
            self._close_popup()
        else:
            self._show_popup()

    def _show_popup(self):
        CredPopup.close_existing()
        self._popup = CredPopup()
        self._popup.destroyed.connect(self._on_popup_closed)
        self._popup.show_at(self._full_value, self._value_label)
        self._is_showing = True
        self._value_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px; color: #2196F3;"
        )

    def _on_popup_closed(self):
        self._popup = None
        self._is_showing = False
        self._value_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px; color: #555;"
        )

    def _close_popup(self):
        if self._popup:
            self._popup.close()
