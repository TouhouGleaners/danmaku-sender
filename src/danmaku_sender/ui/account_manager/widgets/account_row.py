"""单条账号行：昵称 + 状态 + 凭据 + 操作按钮"""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton

from .cred_line import CredLine

from danmaku_sender.core.models.account import AccountCredential
from danmaku_sender.ui.framework.style_loader import get_svg_icon


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
        if is_active:
            accent.setStyleSheet("background: #2196F3; border-radius: 1px;")
        else:
            accent.setStyleSheet("background: transparent;")
        layout.addWidget(accent)

        # 右侧信息区
        right = QVBoxLayout()
        right.setSpacing(4)

        # 第一行：昵称 + 状态 + 按钮
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        display_name = account.name or "未知用户"
        name_label = QLabel(display_name)
        name_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        top_row.addWidget(name_label)

        self._status_label = QLabel()
        self._update_status(account.is_valid)
        top_row.addWidget(self._status_label)

        top_row.addStretch()

        right.addLayout(top_row)

        # 第二行：凭据
        cred_row = QHBoxLayout()
        cred_row.setSpacing(16)
        cred_row.addWidget(CredLine("SESSDATA", account.sessdata))
        cred_row.addWidget(CredLine("bili_jct", account.bili_jct))
        cred_row.addStretch()
        right.addLayout(cred_row)

        layout.addLayout(right, 1)

        icon_btns = [
            ("how_to_reg.svg", "使用", self.use_clicked),
            ("troubleshoot.svg", "检测", self.check_clicked),
            ("edit.svg", "编辑", self.edit_clicked),
            ("delete.svg", "删除", self.delete_clicked),
        ]
        for icon_name, tooltip, signal in icon_btns:
            btn = QPushButton()
            btn.setIcon(get_svg_icon(icon_name, color="#434343"))
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
            self._status_label.setText("✓ 有效")
            self._status_label.setStyleSheet("color: #4CAF50; font-size: 12px;")
        elif is_valid is False:
            self._status_label.setText("✗ 失效")
            self._status_label.setStyleSheet("color: #E53935; font-size: 12px;")
        else:
            self._status_label.setText("未检测")
            self._status_label.setStyleSheet("color: #999; font-size: 12px;")
