"""单条账号行：头像 + 昵称 + 状态 + 凭据 + 操作按钮"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton

from ..models import AccountData
from .cred_line import CredLine


class AccountRow(QFrame):
    """单个账号的展示卡片"""

    edit_clicked = Signal(object)    # AccountData
    delete_clicked = Signal(object)  # AccountData
    check_clicked = Signal(object)   # AccountData

    def __init__(self, account: AccountData, parent=None):
        super().__init__(parent)
        self.account = account
        self.setFixedHeight(72)
        self.setObjectName("accountRow")
        self.setStyleSheet("""
            QFrame#accountRow {
                background: white;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
            }
            QFrame#accountRow:hover {
                border-color: #bdbdbd;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # 圆形头像
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

        status_label = self._make_status_label(account.is_valid)
        top_row.addWidget(status_label)

        top_row.addStretch()

        btn_check = QPushButton("🔍")
        btn_check.setFixedSize(28, 28)
        btn_check.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_check.setToolTip("检测登录状态")
        btn_check.clicked.connect(lambda: self.check_clicked.emit(self.account))
        btn_check.setStyleSheet(self._icon_btn_style())
        top_row.addWidget(btn_check)

        btn_edit = QPushButton("✎")
        btn_edit.setFixedSize(28, 28)
        btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_edit.setToolTip("编辑")
        btn_edit.clicked.connect(lambda: self.edit_clicked.emit(self.account))
        btn_edit.setStyleSheet(self._icon_btn_style())
        top_row.addWidget(btn_edit)

        btn_del = QPushButton("✕")
        btn_del.setFixedSize(28, 28)
        btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del.setToolTip("删除")
        btn_del.clicked.connect(lambda: self.delete_clicked.emit(self.account))
        btn_del.setStyleSheet(self._icon_btn_style_hover_red())
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

    def _make_avatar(self, letter: str, color: str) -> QPixmap:
        """生成圆形字母头像"""
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

    def _make_status_label(self, is_valid: bool | None) -> QLabel:
        label = QLabel()
        if is_valid is True:
            label.setText("✓ 有效")
            label.setStyleSheet(
                "color: #4CAF50; background: #E8F5E9; padding: 2px 8px; "
                "border-radius: 10px; font-size: 11px;"
            )
        elif is_valid is False:
            label.setText("✗ 失效")
            label.setStyleSheet(
                "color: #E53935; background: #FFEBEE; padding: 2px 8px; "
                "border-radius: 10px; font-size: 11px;"
            )
        else:
            label.setText("未检测")
            label.setStyleSheet(
                "color: #999; background: #f5f5f5; padding: 2px 8px; "
                "border-radius: 10px; font-size: 11px;"
            )
        return label

    @staticmethod
    def _icon_btn_style() -> str:
        return """
            QPushButton { background: transparent; border: none; border-radius: 14px;
                          font-size: 14px; }
            QPushButton:hover { background: #f0f0f0; }
        """

    @staticmethod
    def _icon_btn_style_hover_red() -> str:
        return """
            QPushButton { background: transparent; border: none; border-radius: 14px;
                          font-size: 14px; }
            QPushButton:hover { background: #FFEBEE; color: #E53935; }
        """
