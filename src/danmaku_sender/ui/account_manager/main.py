"""账号管理主窗口"""
import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QLabel, QWidget, QMessageBox
)

from .models import AccountData
from .widgets.account_row import AccountRow
from .dialogs.account_form import AccountFormDialog

from ...core.models.account import AccountCredential
from ...core.state import AppState, ApiAuthConfig
from ...ui.framework.concurrency import PoolTask
from ...api.bili_api_client import BiliApiClient

logger = logging.getLogger("App.System.Account")


def _credential_to_data(acc: AccountCredential) -> AccountData:
    return AccountData(
        nickname=acc.name or "未知用户",
        sessdata=acc.sessdata,
        bili_jct=acc.bili_jct,
    )


def _data_to_credential(data: AccountData, uid: int = 0) -> AccountCredential:
    return AccountCredential(
        uid=uid,
        name=data.nickname if data.nickname != "未知用户" else "",
        sessdata=data.sessdata,
        bili_jct=data.bili_jct,
    )


class AccountDialog(QDialog):
    """账号管理主窗口"""

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("账号管理")
        self.setFixedSize(680, 480)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.CustomizeWindowHint
        )

        self.accounts: list[AccountData] = [
            _credential_to_data(a) for a in state.saved_accounts
        ]

        self._create_ui()
        self._refresh()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 标题栏
        header = QHBoxLayout()
        title = QLabel("账号管理")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        header.addWidget(title)
        self._count_label = QLabel()
        self._count_label.setStyleSheet("color: #999; font-size: 12px;")
        header.addWidget(self._count_label)
        header.addStretch()
        layout.addLayout(header)

        # 滚动区域
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._scroll_container = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_container)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(8)
        self._scroll_layout.addStretch()
        self._scroll.setWidget(self._scroll_container)

        layout.addWidget(self._scroll, 1)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_add = QPushButton("添加账号")
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.clicked.connect(self._add_account)
        btn_row.addWidget(btn_add)
        layout.addLayout(btn_row)

    def _refresh(self):
        while self._scroll_layout.count() > 1:
            item = self._scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for acc in self.accounts:
            row = AccountRow(acc)
            row.edit_clicked.connect(self._edit_account)
            row.delete_clicked.connect(self._delete_account)
            row.check_clicked.connect(self._check_account)
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, row)

        self._count_label.setText(f"共 {len(self.accounts)} 个账号")

    def _add_account(self):
        proxy = self.state.sender_config.use_system_proxy
        dialog = AccountFormDialog(edit_data=None, use_system_proxy=proxy, parent=self)
        dialog.saved.connect(self._on_account_saved)
        dialog.exec()

    def _edit_account(self, account: AccountData):
        dialog = AccountFormDialog(edit_data=account, parent=self)
        dialog.saved.connect(lambda _: self._refresh())
        dialog.exec()

    def _delete_account(self, account: AccountData):
        reply = QMessageBox.question(
            self, "删除账号",
            f"确定要删除账号「{account.nickname}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.accounts.remove(account)
            self._refresh()

    def _check_account(self, account: AccountData):
        config = ApiAuthConfig(
            sessdata=account.sessdata,
            bili_jct=account.bili_jct,
            use_system_proxy=self.state.sender_config.use_system_proxy
        )
        PoolTask.submit(
            self._do_check,
            lambda result: self._on_check_result(account, result),
            lambda _: self._on_check_result(account, False),
            config,
        )

    @staticmethod
    def _do_check(config) -> bool:
        try:
            with BiliApiClient.from_config(config) as client:
                nav = client.get_user_info()
                return bool(nav.get('isLogin'))
        except Exception:
            return False

    def _on_check_result(self, account: AccountData, is_valid: bool):
        account.is_valid = is_valid
        if is_valid:
            config = ApiAuthConfig(
                sessdata=account.sessdata,
                bili_jct=account.bili_jct,
                use_system_proxy=self.state.sender_config.use_system_proxy
            )
            try:
                with BiliApiClient.from_config(config) as client:
                    nav = client.get_user_info()
                    account.nickname = nav.get('uname', account.nickname)
            except Exception:
                pass
        self._refresh()

    def _on_account_saved(self, account: AccountData):
        self.accounts.append(account)
        self._refresh()

    def _sync_state(self):
        self.state.saved_accounts = [
            _data_to_credential(a) for a in self.accounts
        ]

    def accept(self):
        self._sync_state()
        super().accept()

    def reject(self):
        self._sync_state()
        super().reject()
