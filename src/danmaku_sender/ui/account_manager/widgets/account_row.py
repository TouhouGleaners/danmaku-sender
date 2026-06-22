"""单条账号行：头像 + 昵称 + 状态 + 凭据 + 操作按钮"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton

from ..models import AccountData
from .cred_line import CredLine


class AccountRow(QFrame):
    """单个账号的展示卡片"""

    use_clicked = Signal(object)     # AccountData
    edit_clicked = Signal(object)    # AccountData
    delete_clicked = Signal(object)  # AccountData
    check_clicked = Signal(object)   # AccountData

    def __init__(self, account: AccountData, parent=None):
        super().__init__(parent)
        self.account = account
        self.setFixedHeight(72)
        self.setObjectName("accountRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # 圆形字母头像
        avatar = QLabel()
        avatar.setFixedSize(44, 44)
        avatar.setPixmap(self._make_avatar(account.initial, account.color))
        layout.addWidget(avatar)

        # 右侧信息区
        right = QVBoxLayout()
        right.setSpacing(4)

        # 第一行：昵称 + 状态 + 按钮
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        name_label = QLabel(account.nickname)
        name_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        top_row.addWidget(name_label)

        self._status_label = QLabel()
        self._update_status(account.is_valid)
        top_row.addWidget(self._status_label)

        top_row.addStretch()

        btn_use = QPushButton("使用")
        btn_use.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_use.clicked.connect(lambda: self.use_clicked.emit(self.account))
        top_row.addWidget(btn_use)

        btn_check = QPushButton("检测")
        btn_check.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_check.clicked.connect(lambda: self.check_clicked.emit(self.account))
        top_row.addWidget(btn_check)

        btn_edit = QPushButton("编辑")
        btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_edit.clicked.connect(lambda: self.edit_clicked.emit(self.account))
        top_row.addWidget(btn_edit)

        btn_del = QPushButton("删除")
        btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del.clicked.connect(lambda: self.delete_clicked.emit(self.account))
        top_row.addWidget(btn_del)

        right.addLayout(top_row)

        # 第二行：凭据
        cred_row = QHBoxLayout()
        cred_row.setSpacing(16)
        cred_row.addWidget(CredLine("SESSDATA", account.sessdata))
        cred_row.addWidget(CredLine("bili_jct", account.bili_jct))
        cred_row.addStretch()
        right.addLayout(cred_row)

        layout.addLayout(right, 1)

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

    def _make_avatar(self, letter: str, color: str) -> QPixmap:
        size = 44
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor("transparent"))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, size, size)

        painter.setPen(QColor("white"))
        font = QFont("Arial", 18, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, letter)
        painter.end()
        return pixmap
