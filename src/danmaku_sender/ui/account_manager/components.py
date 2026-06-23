"""账号管理子组件：凭据弹出框、凭据行、账号卡片"""
from typing import Callable

from PySide6.QtCore import QSize, Qt, QEvent, QObject, QPoint, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QWidget,
    QApplication, QScrollArea, QSizePolicy,
)

from danmaku_sender.core.models.account import AccountCredential
from danmaku_sender.ui.framework.style_loader import get_svg_icon


# ── CredPopup 凭据弹出框 ──────────────────────────────────────────

_popup: 'CredPopup | None' = None
_popup_close_cb: Callable[[], None] | None = None


class CredPopup(QWidget):
    """父窗口内的浮层控件（单例），eventFilter 检测点击外部区域关闭"""

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
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress and self.isVisible():
            local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
            if not self.rect().contains(local_pos):
                self.hide()
        return False

    def _on_copy(self):
        QApplication.clipboard().setText(self._full_value)
        self._copy_btn.setText("✓")
        QTimer.singleShot(1200, lambda: self._copy_btn.setText("复制"))

    def hideEvent(self, event):
        global _popup_close_cb
        if _popup_close_cb:
            try:
                _popup_close_cb()
            except RuntimeError:
                _popup_close_cb = None
        super().hideEvent(event)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)


def show_popup(full_value: str, anchor: QWidget, on_close: Callable[[], None] | None = None):
    """在 anchor 控件正上方显示凭据弹出框"""
    global _popup, _popup_close_cb
    _popup_close_cb = on_close

    parent = anchor.window()
    if _popup is None or _popup.parent() is not parent:
        if _popup:
            _popup.deleteLater()
        _popup = CredPopup(parent)

    _popup._full_value = full_value
    _popup._value_label.setText(full_value)
    _popup._copy_btn.setText("复制")
    _popup.adjustSize()

    anchor_pos = anchor.mapTo(parent, QPoint(0, 0))
    x = anchor_pos.x()
    y = anchor_pos.y() - _popup.height() - 4
    _popup.move(x, max(0, y))
    _popup.show()
    _popup.raise_()


def close_popup():
    global _popup
    if _popup and _popup.isVisible():
        _popup.hide()


def is_popup_visible() -> bool:
    return _popup is not None and _popup.isVisible()


# ── CredLine 凭据显示行 ────────────────────────────────────────────

_active_cred_line: 'CredLine | None' = None


class CredLine(QWidget):
    """单个凭据字段的遮蔽显示，点击可弹出完整值"""

    def __init__(self, prefix: str, masked_value: str, full_value: str, parent=None):
        super().__init__(parent)
        self._full_value = full_value

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        prefix_label = QLabel(f"{prefix}:")
        prefix_label.setObjectName("credPrefix")
        layout.addWidget(prefix_label)

        self._value_label = QLabel(masked_value)
        self._value_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._value_label.setWordWrap(False)
        self._value_label.setObjectName("credValue")
        self._set_normal_style()
        self._value_label.mousePressEvent = self._on_click
        layout.addWidget(self._value_label)

        layout.addStretch()

    def _on_click(self, event):
        global _active_cred_line
        if is_popup_visible():
            close_popup()
            return
        _active_cred_line = self
        self._value_label.setProperty("active", True)
        self._value_label.style().unpolish(self._value_label)
        self._value_label.style().polish(self._value_label)
        show_popup(self._full_value, self._value_label, on_close=self._on_popup_closed)

    def _on_popup_closed(self):
        global _active_cred_line
        if _active_cred_line:
            _active_cred_line._set_normal_style()
            _active_cred_line = None

    def _set_normal_style(self):
        self._value_label.setProperty("active", False)
        self._value_label.style().unpolish(self._value_label)
        self._value_label.style().polish(self._value_label)


# ── AccountRow 账号行 ──────────────────────────────────────────────

class AccountRow(QFrame):
    """单个账号的展示卡片"""

    use_clicked = Signal(AccountCredential)
    edit_clicked = Signal(AccountCredential)
    delete_clicked = Signal(AccountCredential)
    check_clicked = Signal(AccountCredential)

    def __init__(self, account: AccountCredential, is_active: bool = False, parent=None):
        super().__init__(parent)
        self.account = account
        self.setFixedHeight(72)
        self.setObjectName("accountRow")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("active", is_active)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # 左侧激活指示条
        accent = QFrame()
        accent.setFixedSize(3, 40)
        accent.setObjectName("accountAccent")
        accent.setProperty("active", is_active)
        layout.addWidget(accent)

        # 右侧信息区
        right = QVBoxLayout()
        right.setSpacing(4)

        # 第一行：昵称 + 状态
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        display_name = account.name or "未知用户"
        name_label = QLabel(display_name)
        name_label.setObjectName("accountName")
        top_row.addWidget(name_label)

        self._status_icon = QLabel()
        self._status_text = QLabel()
        self._status_text.setObjectName("accountStatus")
        self._update_status(account.is_valid)
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(4)
        status_layout.addWidget(self._status_icon)
        status_layout.addWidget(self._status_text)
        top_row.addWidget(status_widget)

        top_row.addStretch()

        right.addLayout(top_row)

        # 第二行：凭据
        cred_row = QHBoxLayout()
        cred_row.setSpacing(16)
        cred_row.addWidget(CredLine("SESSDATA", account.masked_sessdata, account.sessdata))
        cred_row.addWidget(CredLine("bili_jct", account.masked_bili_jct, account.bili_jct))
        cred_row.addStretch()
        right.addLayout(cred_row)

        layout.addLayout(right, 1)

        # 右侧操作按钮
        icon_btns = [
            ("how_to_reg.svg", "使用", self.use_clicked),
            ("troubleshoot.svg", "检测", self.check_clicked),
            ("edit.svg", "编辑", self.edit_clicked),
            ("delete.svg", "删除", self.delete_clicked),
        ]
        for icon_name, tooltip, signal in icon_btns:
            btn = QPushButton()
            btn.setIcon(get_svg_icon(icon_name))
            btn.setIconSize(QSize(20, 20))
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedSize(32, 32)
            btn.setObjectName("accountIconBtn")
            btn.clicked.connect(lambda checked=False, s=signal: s.emit(self.account))
            layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignVCenter)

    def mouseDoubleClickEvent(self, event):
        self.use_clicked.emit(self.account)
        super().mouseDoubleClickEvent(event)

    def _update_status(self, is_valid: bool | None):
        if is_valid is True:
            self._status_icon.setPixmap(get_svg_icon("check_circle.svg", "#4CAF50").pixmap(16, 16))
            self._status_text.setText("有效")
            self._status_text.setProperty("status", "valid")
        elif is_valid is False:
            self._status_icon.setPixmap(get_svg_icon("cancel.svg", "#E53935").pixmap(16, 16))
            self._status_text.setText("失效")
            self._status_text.setProperty("status", "invalid")
        else:
            self._status_icon.setPixmap(get_svg_icon("help.svg", "#999").pixmap(16, 16))
            self._status_text.setText("未检测")
            self._status_text.setProperty("status", "unknown")
        self._status_text.style().unpolish(self._status_text)
        self._status_text.style().polish(self._status_text)
