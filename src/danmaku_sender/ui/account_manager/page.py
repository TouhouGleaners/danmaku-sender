"""账号管理主窗口"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QLabel, QWidget, QMessageBox,
)

from .components import AccountRow
from .account_form import AccountFormDialog

from danmaku_sender.core.models.account import AccountCredential
from danmaku_sender.core.config import ApiAuthConfig
from danmaku_sender.runtime.app_state import AppState
from danmaku_sender.ui.controllers.account_controller import AccountController
from danmaku_sender.ui.framework.style_loader import get_svg_icon

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

        self._batch_total: int = 0
        self._batch_done: int = 0
        self._rows: list[AccountRow] = []
        self._is_batching: bool = False

        self._controller = AccountController(self)
        self._controller.checkFinished.connect(self._on_check_finished)
        self._controller.userInfoFetched.connect(self._on_user_info_fetched)

        self._create_ui()
        self._refresh()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 标题栏
        header = QHBoxLayout()
        self._title_label = QLabel("账号管理")
        self._title_label.setObjectName("accountDialogTitle")
        header.addWidget(self._title_label)
        self._count_label = QLabel()
        self._count_label.setObjectName("accountDialogCount")
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
        self._btn_clear = QPushButton("清除失效")
        self._btn_clear.setIcon(get_svg_icon("delete_sweep.svg"))
        self._btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_clear.clicked.connect(self._clear_invalid)
        self._btn_clear.setEnabled(False)
        btn_row.addWidget(self._btn_clear)

        self._btn_check_all = QPushButton("全部检测")
        self._btn_check_all.setIcon(get_svg_icon("troubleshoot.svg"))
        self._btn_check_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_check_all.clicked.connect(self._check_all)
        btn_row.addWidget(self._btn_check_all)

        btn_row.addStretch()

        btn_add = QPushButton("添加账号")
        btn_add.setIcon(get_svg_icon("person_add.svg"))
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.clicked.connect(self._add_account)
        btn_row.addWidget(btn_add)
        layout.addLayout(btn_row)

    def _refresh(self):
        while self._scroll_layout.count() > 1:
            item = self._scroll_layout.takeAt(0)
            if item and (w := item.widget()):
                w.deleteLater()

        self._rows.clear()
        for acc in self.accounts:
            is_active = acc.sessdata == self.state.sessdata
            row = AccountRow(acc, is_active=is_active)
            row.add_cred("SESSDATA", acc.masked_sessdata, acc.sessdata)
            row.add_cred("bili_jct", acc.masked_bili_jct, acc.bili_jct)
            row.use_clicked.connect(self._use_account)
            row.edit_clicked.connect(self._edit_account)
            row.delete_clicked.connect(self._delete_account)
            row.check_clicked.connect(self._check_account)
            if self._is_batching:
                row.set_check_enabled(False)
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, row)
            self._rows.append(row)

        self._count_label.setText(f"共 {len(self.accounts)} 个账号")
        if not self._is_batching:
            self._btn_clear.setEnabled(any(a.is_valid is False for a in self.accounts))

    def _make_config(self, account: AccountCredential) -> ApiAuthConfig:
        return ApiAuthConfig(
            sessdata=account.sessdata,
            bili_jct=account.bili_jct,
            use_system_proxy=self.state.sender_config.use_system_proxy,
        )

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
        proxy = self.state.sender_config.use_system_proxy
        dialog = AccountFormDialog(edit_data=account, use_system_proxy=proxy, parent=self)
        dialog.saved.connect(lambda new, _old: self._on_edit_saved(new, account))
        dialog.exec()

    def _is_duplicate(self, sessdata: str, exclude: AccountCredential | None = None) -> bool:
        """检查 SESSDATA 是否已存在（可排除指定账号）"""
        return any(acc is not exclude and acc.sessdata == sessdata for acc in self.accounts)

    def _on_edit_saved(self, new: AccountCredential, old: AccountCredential):
        if self._is_duplicate(new.sessdata, exclude=old):
            QMessageBox.warning(self, "重复账号", "该 SESSDATA 已存在，不可重复添加。")
            return
        old.sessdata = new.sessdata
        old.bili_jct = new.bili_jct
        old.is_valid = None
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
        self._controller.check_account(account, self._make_config(account))

    def _on_check_finished(self, account: AccountCredential, is_valid: bool):
        account.is_valid = is_valid
        if is_valid:
            self._controller.fetch_user_info(account, self._make_config(account))

        if self._batch_total > 0:
            self._batch_done += 1
            self._title_label.setText(f"检测中 {self._batch_done}/{self._batch_total}...")
            if self._batch_done >= self._batch_total:
                self._finish_batch()

        self._refresh()

    def _check_all(self):
        if not self.accounts:
            return
        self._batch_total = len(self.accounts)
        self._batch_done = 0
        self._is_batching = True
        self._btn_check_all.setEnabled(False)
        self._btn_clear.setEnabled(False)
        self._title_label.setText(f"检测中 0/{self._batch_total}...")
        for row in self._rows:
            row.set_check_enabled(False)

        for acc in self.accounts:
            self._controller.check_account(acc, self._make_config(acc))

    def _finish_batch(self):
        self._batch_total = 0
        self._batch_done = 0
        self._is_batching = False
        self._btn_check_all.setEnabled(True)
        self._title_label.setText("账号管理")
        for row in self._rows:
            row.set_check_enabled(True)

    def _clear_invalid(self):
        invalid_count = sum(1 for a in self.accounts if a.is_valid is False)
        if not invalid_count:
            return
        reply = QMessageBox.question(
            self, "清除失效账号",
            f"确定要删除 {invalid_count} 个失效账号吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.accounts = [a for a in self.accounts if a.is_valid is not False]
            self._refresh()

    def _on_account_saved(self, new: AccountCredential, _old: AccountCredential):
        if self._is_duplicate(new.sessdata):
            QMessageBox.warning(self, "重复账号", "该 SESSDATA 已存在，不可重复添加。")
            return
        self.accounts.append(new)
        self._refresh()

        self._controller.fetch_user_info(new, self._make_config(new))

    def _on_user_info_fetched(self, account: AccountCredential, info: dict | None):
        if not info or not info.get('isLogin'):
            return
        account.uid = info.get('mid', 0)
        account.name = info.get('uname', account.name)
        duplicate = next(
            (a for a in self.accounts if a is not account and a.uid == account.uid and a.uid != 0),
            None,
        )
        if duplicate:
            self.accounts.remove(duplicate)
            logger.info(f"合并重复账号: {duplicate.name} → {account.name}")
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
