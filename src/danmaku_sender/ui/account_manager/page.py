"""账号管理主窗口"""
import logging
from typing import Callable

from PySide6.QtCore import QSize, Qt, QEvent, QObject, QPoint, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QPushButton, QLabel, QWidget, QMessageBox,
    QApplication, QSizePolicy,
)

from .account_form import AccountFormDialog

from danmaku_sender.core.models.account import AccountCredential, _mask
from danmaku_sender.core.state import AppState, ApiAuthConfig
from danmaku_sender.ui.controllers.account_controller import AccountController
from danmaku_sender.ui.framework.style_loader import get_svg_icon

logger = logging.getLogger("App.System.Account")


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

    def __init__(self, prefix: str, full_value: str, parent=None):
        super().__init__(parent)
        self._full_value = full_value

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        prefix_label = QLabel(f"{prefix}:")
        prefix_label.setObjectName("credPrefix")
        layout.addWidget(prefix_label)

        self._value_label = QLabel(_mask(full_value))
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
        cred_row.addWidget(CredLine("SESSDATA", account.sessdata))
        cred_row.addWidget(CredLine("bili_jct", account.bili_jct))
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


# ── AccountDialog 账号管理主窗口 ───────────────────────────────────

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

        self._checking_account: AccountCredential | None = None
        self._fetching_account: AccountCredential | None = None

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
        title = QLabel("账号管理")
        title.setObjectName("accountDialogTitle")
        header.addWidget(title)
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

    def _make_config(self, account: AccountCredential) -> ApiAuthConfig:
        return ApiAuthConfig(
            sessdata=account.sessdata,
            bili_jct=account.bili_jct,
            use_system_proxy=self.state.sender_config.use_system_proxy,
        )

    def _check_account(self, account: AccountCredential):
        self._checking_account = account
        self._controller.check_account(self._make_config(account))

    def _on_check_finished(self, is_valid: bool):
        account = self._checking_account
        account.is_valid = is_valid
        if is_valid:
            self._fetching_account = account
            self._controller.fetch_user_info(self._make_config(account))
        self._refresh()

    def _on_account_saved(self, account: AccountCredential):
        for acc in self.accounts:
            if acc.sessdata == account.sessdata:
                QMessageBox.warning(self, "重复账号", "该 SESSDATA 已存在，不可重复添加。")
                return
        self.accounts.append(account)
        self._refresh()

        self._fetching_account = account
        self._controller.fetch_user_info(self._make_config(account))

    def _on_user_info_fetched(self, info: dict | None):
        account = self._fetching_account
        if not account or not info or not info.get('isLogin'):
            return
        account.uid = info.get('mid', 0)
        account.name = info.get('uname', account.name)
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
