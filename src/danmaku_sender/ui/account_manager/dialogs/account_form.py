"""添加/编辑账号弹窗（共用）"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QLabel, QLineEdit, QTabBar, QFormLayout, QWidget
)

from ..models import AccountData
from ...controllers.auth_controller import AuthController
from ...dialogs import QRLoginDialog


class AccountFormDialog(QDialog):
    """添加/编辑账号弹窗"""

    saved = Signal(AccountData)

    def __init__(self, edit_data: AccountData | None = None, use_system_proxy: bool = True, parent=None):
        super().__init__(parent)
        self._edit_data = edit_data
        self._use_system_proxy = use_system_proxy
        self._result: AccountData | None = None

        is_edit = edit_data is not None
        self.setWindowTitle("编辑账号" if is_edit else "添加账号")
        self.setFixedSize(460, 430)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.CustomizeWindowHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Tab 栏（编辑模式隐藏）
        self._tab_bar = QTabBar()
        self._tab_bar.addTab("扫码登录")
        self._tab_bar.addTab("手动输入")
        self._tab_bar.setHidden(is_edit)
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tab_bar)

        # StackedWidget
        self._stack = QStackedWidget()

        # Page 0: 扫码
        self._qr_page = self._build_qr_page()
        self._stack.addWidget(self._qr_page)

        # Page 1: 手动输入
        self._manual_page = self._build_manual_page(edit_data)
        self._stack.addWidget(self._manual_page)

        if is_edit:
            self._stack.setCurrentIndex(1)

        layout.addWidget(self._stack, 1)

        # 错误提示
        self._error_label = QLabel()
        self._error_label.setStyleSheet("color: #E53935; font-size: 12px;")
        self._error_label.hide()
        layout.addWidget(self._error_label)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._submit_btn = QPushButton("保存" if is_edit else "添加")
        self._submit_btn.setFixedWidth(100)
        self._submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._submit_btn.setStyleSheet("""
            QPushButton { background: #2196F3; color: white; border: none; border-radius: 6px;
                          padding: 8px 16px; font-size: 13px; }
            QPushButton:hover { background: #1976D2; }
            QPushButton:disabled { background: #ccc; }
        """)
        self._submit_btn.clicked.connect(self._on_submit)
        btn_row.addWidget(self._submit_btn)
        layout.addLayout(btn_row)

    def _build_qr_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 20, 0, 0)
        layout.setSpacing(12)

        self._qr_status = QLabel("点击下方按钮开始扫码登录")
        self._qr_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_status.setStyleSheet("color: #666; font-size: 13px;")
        layout.addWidget(self._qr_status)

        self._qr_btn = QPushButton("开始扫码")
        self._qr_btn.setFixedWidth(140)
        self._qr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._qr_btn.clicked.connect(self._start_qr)
        self._qr_btn.setStyleSheet("""
            QPushButton { background: #4CAF50; color: white; border: none; border-radius: 6px;
                          padding: 10px 20px; font-size: 13px; }
            QPushButton:hover { background: #388E3C; }
        """)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._qr_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addStretch()
        return page

    def _build_manual_page(self, edit_data: AccountData | None) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)

        form = QFormLayout()
        form.setSpacing(12)

        self._se_input = QLineEdit()
        self._se_input.setPlaceholderText("请输入 SESSDATA")
        self._se_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._se_input.setStyleSheet(self._input_style())

        self._jct_input = QLineEdit()
        self._jct_input.setPlaceholderText("请输入 bili_jct")
        self._jct_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._jct_input.setStyleSheet(self._input_style())

        if edit_data:
            self._se_input.setText(edit_data.sessdata)
            self._jct_input.setText(edit_data.bili_jct)

        form.addRow("SESSDATA:", self._se_input)
        form.addRow("bili_jct:", self._jct_input)
        layout.addLayout(form)
        layout.addStretch()
        return page

    def _on_tab_changed(self, index: int):
        self._stack.setCurrentIndex(index)
        self._error_label.hide()

    def _start_qr(self):
        dialog = QRLoginDialog(self._use_system_proxy, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            cookies = dialog.cookies
            se = cookies.get('SESSDATA', '')
            jct = cookies.get('bili_jct', '')
            if se and jct:
                self._result = AccountData(sessdata=se, bili_jct=jct)
                self.saved.emit(self._result)
                self.accept()

    def _on_submit(self):
        se = self._se_input.text().strip()
        jct = self._jct_input.text().strip()
        if not se or not jct:
            self._error_label.setText("⚠ SESSDATA 和 bili_jct 均不能为空")
            self._error_label.show()
            self._tab_bar.setCurrentIndex(1)
            return

        if self._edit_data:
            self._edit_data.sessdata = se
            self._edit_data.bili_jct = jct
            self._edit_data.is_valid = None  # 重置检测状态
            self.saved.emit(self._edit_data)
        else:
            self._result = AccountData(sessdata=se, bili_jct=jct)
            self.saved.emit(self._result)

        self.accept()

    @staticmethod
    def _input_style() -> str:
        return """
            QLineEdit {
                border: 2px solid #e0e0e0; border-radius: 8px;
                padding: 10px 14px; font-size: 13px;
            }
            QLineEdit:focus { border-color: #2196F3; }
        """
