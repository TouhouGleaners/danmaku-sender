"""账号管理子组件：账号卡片"""
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QWidget,
    QApplication,
)

from danmaku_sender.core.models.account import AccountCredential
from danmaku_sender.ui.framework.style_loader import get_svg_icon


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

        # 第二行：凭据（由 add_cred 填充）
        self._cred_row = QHBoxLayout()
        self._cred_row.setSpacing(16)
        right.addLayout(self._cred_row)

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

    def add_cred(self, prefix: str, masked_value: str, full_value: str):
        """添加一个凭据字段：单击遮蔽值复制到剪贴板"""
        label = QLabel(f"{prefix}: {masked_value}")
        label.setObjectName("credValue")
        label.setCursor(Qt.CursorShape.PointingHandCursor)

        def _on_click(_event):
            QApplication.clipboard().setText(full_value)
            label.setText(f"{prefix}: 已复制")
            QTimer.singleShot(500, lambda: label.setText(f"{prefix}: {masked_value}"))

        label.mousePressEvent = _on_click
        self._cred_row.addWidget(label)

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
