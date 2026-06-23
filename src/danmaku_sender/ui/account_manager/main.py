"""账号管理主窗口"""
import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QLabel, QWidget, QMessageBox
)

from .widgets.account_row import AccountRow
from .dialogs.account_form import AccountFormDialog

from danmaku_sender.core.models.account import AccountCredential
from danmaku_sender.core.state import AppState, ApiAuthConfig
from danmaku_sender.ui.framework.concurrency import PoolTask
from danmaku_sender.api.bili_api_client import BiliApiClient

logger = logging.getLogger("App.System.Account")


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

        self.accounts: list[AccountCredential] = [
            a.model_copy() for a in state.saved_accounts
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
        self._scroll_layout.setSpacing(0)
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
            is_active = acc.sessdata == self.state.sessdata
            row = AccountRow(acc, is_active=is_active)
            row.use_clicked.connect(self._use_account)
            row.edit_clicked.connect(self._edit_account)
            row.delete_clicked.connect(self._delete_account)
            row.check_clicked.connect(self._check_account)
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, row)

        self._count_label.setText(f"共 {len(self.accounts)} 个账号")

    def _use_account(self, account: AccountCredential):
        if account.sessdata == self.state.sessdata:
            return
        self.state.sessdata = account.sessdata
        self.state.bili_jct = account.bili_jct
        self.accept()

    def _add_account(self):
        proxy = self.state.sender_config.use_system_proxy
        dialog = AccountFormDialog(edit_data=None, use_system_proxy=proxy, parent=self)
        dialog.saved.connect(self._on_account_saved)
        dialog.exec()

    def _edit_account(self, account: AccountCredential):
        dialog = AccountFormDialog(edit_data=account, parent=self)
        dialog.saved.connect(lambda _: self._on_edit_saved(account))
        dialog.exec()

    def _on_edit_saved(self, account: AccountCredential):
        # account 已被 dialog 就地修改，只需检查重复
        for acc in self.accounts:
            if acc is not account and acc.sessdata == account.sessdata:
                QMessageBox.warning(self, "重复账号", "该 SESSDATA 已存在，不可重复添加。")
                return
        self._refresh()

    def _delete_account(self, account: AccountCredential):
        display_name = account.name or "未知用户"
        reply = QMessageBox.question(
            self, "删除账号",
            f"确定要删除账号「{display_name}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.accounts.remove(account)
            self._refresh()

    def _check_account(self, account: AccountCredential):
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

    def _on_check_result(self, account: AccountCredential, is_valid: bool):
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
                    account.name = nav.get('uname', account.name)
                    if not account.uid:
                        account.uid = nav.get('mid', 0)
            except Exception:
                pass
        self._refresh()

    def _on_account_saved(self, account: AccountCredential):
        # 快速检查：sessdata 重复
        for acc in self.accounts:
            if acc.sessdata == account.sessdata:
                QMessageBox.warning(self, "重复账号", "该 SESSDATA 已存在，不可重复添加。")
                return
        self.accounts.append(account)
        self._refresh()

        # 异步获取 uid，用于同用户凭证更新时去重
        config = ApiAuthConfig(
            sessdata=account.sessdata,
            bili_jct=account.bili_jct,
            use_system_proxy=self.state.sender_config.use_system_proxy
        )
        PoolTask.submit(
            self._do_fetch_user_info,
            lambda info: self._on_user_info_fetched(account, info),
            lambda _: None,
            config,
        )

    @staticmethod
    def _do_fetch_user_info(config) -> dict | None:
        try:
            with BiliApiClient.from_config(config) as client:
                return client.get_user_info()
        except Exception:
            return None

    def _on_user_info_fetched(self, account: AccountCredential, info: dict | None):
        if not info or not info.get('isLogin'):
            return
        account.uid = info.get('mid', 0)
        account.name = info.get('uname', account.name)
        # uid 去重：合并同用户的旧条目
        for existing in self.accounts:
            if existing is not account and existing.uid == account.uid and existing.uid != 0:
                self.accounts.remove(existing)
                logger.info(f"合并重复账号: {existing.name} → {account.name}")
                break
        self._refresh()

    def _sync_state(self):
        self.state.saved_accounts = [
            a.model_copy() for a in self.accounts
        ]

    def accept(self):
        self._sync_state()
        super().accept()

    def reject(self):
        self._sync_state()
        super().reject()
