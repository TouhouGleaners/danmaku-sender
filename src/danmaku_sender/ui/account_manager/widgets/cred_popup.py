"""凭据弹出框：深色悬浮框，显示完整值 + 复制按钮

实现为父窗口的子 QWidget（非独立窗口），避免 FramelessWindowHint
在 Windows 上的鼠标事件拦截问题。
"""
from typing import Callable

from PySide6.QtCore import Qt, QEvent, QObject, QPoint, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QApplication, QScrollArea, QSizePolicy
)


class CredPopup(QWidget):
    """父窗口内的浮层控件（单例）

    关闭机制：eventFilter 检测点击浮层以外的区域。
    与 CredLine 解耦：通过 _close_callback 类变量注入回调。
    """

    _INSTANCE: 'CredPopup | None' = None
    _close_callback: Callable[[], None] | None = None

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.SubWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setFixedWidth(320)
        self.setMaximumHeight(180)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QWidget()
        container.setObjectName("credPopupContainer")

        inner = QVBoxLayout(container)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.setSpacing(8)

        self._value_label = QLabel()
        self._value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._value_label.setWordWrap(True)
        self._value_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._value_label)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMaximumHeight(120)
        inner.addWidget(scroll)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._copy_btn = QPushButton("复制")
        self._copy_btn.setFixedWidth(60)
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.clicked.connect(self._on_copy)
        btn_row.addWidget(self._copy_btn)
        inner.addLayout(btn_row)

        outer.addWidget(container)

        self._full_value = ""

        self.setStyleSheet("""
            QWidget#credPopupContainer {
                background: #1e1e1e;
                border: 1px solid #444;
                border-radius: 6px;
            }
            QWidget#credPopupContainer QLabel {
                color: #e0e0e0;
                background: transparent;
                font-family: Consolas, monospace;
                font-size: 12px;
            }
            QWidget#credPopupContainer QScrollArea {
                background: transparent;
                border: none;
            }
            QWidget#credPopupContainer QPushButton {
                background: #333;
                color: #e0e0e0;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QWidget#credPopupContainer QPushButton:hover {
                background: #444;
            }
        """)

        QApplication.instance().installEventFilter(self)

    @staticmethod
    def set_close_callback(callback: Callable[[], None] | None):
        """由 CredLine 注入，用于在 popup 隐藏时重置样式"""
        CredPopup._close_callback = callback

    @staticmethod
    def show_popup(full_value: str, anchor_widget: QWidget):
        # 首次或父窗口变化时重建
        parent = anchor_widget.window()
        if CredPopup._INSTANCE is None or CredPopup._INSTANCE.parent() is not parent:
            if CredPopup._INSTANCE:
                CredPopup._INSTANCE.deleteLater()
            CredPopup._INSTANCE = CredPopup(parent)

        popup = CredPopup._INSTANCE
        popup._full_value = full_value
        popup._value_label.setText(full_value)
        popup._copy_btn.setText("复制")
        popup.adjustSize()

        # 在父窗口坐标系中定位到锚控件正上方
        anchor_pos = anchor_widget.mapTo(parent, QPoint(0, 0))
        x = anchor_pos.x()
        y = anchor_pos.y() - popup.height() - 4
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
        if event.type() == QEvent.Type.MouseButtonPress and self.isVisible():
            # mapFromGlobal 正确处理顶级窗口和子控件两种情况
            local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
            if not self.rect().contains(local_pos):
                self.hide()
        return False

    def _on_copy(self):
        QApplication.clipboard().setText(self._full_value)
        self._copy_btn.setText("✓")
        QTimer.singleShot(1200, lambda: self._copy_btn.setText("复制"))

    def hideEvent(self, event):
        if CredPopup._close_callback:
            try:
                CredPopup._close_callback()
            except RuntimeError:
                CredPopup._close_callback = None
        super().hideEvent(event)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)
