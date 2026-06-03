from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QCheckBox, QGroupBox, QPushButton, QDialog, QListWidget, QListWidgetItem, QAbstractItemView
)
from PySide6.QtCore import Qt, Slot

from .framework.binder import UIBinder
from .framework.style_loader import get_svg_icon
from .dialogs import QRLoginDialog

from ..core.state import AppState
from ..core.models.account import AccountCredential
from ..core.models.user import UserProfile


class SettingsPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()

        self.state = state
        self._current_profile: UserProfile | None = None
        self._create_ui()

    def _create_ui(self):
        # 主布局 - 垂直布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # --- 账号管理 ---
        account_group = QGroupBox("账号管理")
        account_layout = QVBoxLayout()

        self.account_list = QListWidget()
        self.account_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.account_list.setMinimumHeight(80)
        self.account_list.setMaximumHeight(160)
        self.account_list.currentRowChanged.connect(self._on_account_selected)
        account_layout.addWidget(self.account_list)

        account_btn_layout = QHBoxLayout()
        self.btn_save_account = QPushButton("保存当前账号")
        self.btn_save_account.clicked.connect(self._save_current_account)
        self.btn_delete_account = QPushButton("删除选中")
        self.btn_delete_account.clicked.connect(self._delete_selected_account)
        self.btn_delete_account.setEnabled(False)
        account_btn_layout.addWidget(self.btn_save_account)
        account_btn_layout.addWidget(self.btn_delete_account)
        account_btn_layout.addStretch()
        account_layout.addLayout(account_btn_layout)

        account_group.setLayout(account_layout)
        main_layout.addWidget(account_group)

        # --- 身份凭证 ---
        auth_group = QGroupBox("身份凭证 (Cookie)")
        auth_layout = QFormLayout()
        auth_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        btn_layout = QHBoxLayout()
        self.btn_qr_login = QPushButton("扫码登录")
        self.btn_qr_login.setIcon(get_svg_icon("qr_scan.svg"))
        self.btn_qr_login.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_qr_login.clicked.connect(self._open_qr_login)

        btn_layout.addWidget(self.btn_qr_login)
        btn_layout.addStretch()

        auth_layout.addRow("", btn_layout)

        # SESSDATA / bili_jct
        self.sessdata_input = QLineEdit()
        self.sessdata_input.setPlaceholderText("请输入您的 SESSDATA")
        self.sessdata_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.sessdata_input.setToolTip("SESSDATA 用于身份验证，请妥善保管。")

        self.bili_jct_input = QLineEdit()
        self.bili_jct_input.setPlaceholderText("请输入您的 bili_jct")
        self.bili_jct_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.bili_jct_input.setToolTip("bili_jct 用于请求验证，请妥善保管。")

        auth_layout.addRow(QLabel("SESSDATA:"), self.sessdata_input)
        auth_layout.addRow(QLabel("bili_jct:"), self.bili_jct_input)

        auth_group.setLayout(auth_layout)
        main_layout.addWidget(auth_group)

        # --- 系统设置 ---
        system_group = QGroupBox("系统设置")
        system_layout = QFormLayout()

        self.prevent_sleep_checkbox = QCheckBox("任务运行时阻止电脑休眠")
        self.prevent_sleep_checkbox.setChecked(True)
        self.prevent_sleep_checkbox.setToolTip("保持网络和CPU运行，但允许屏幕关闭。")

        system_layout.addRow(self.prevent_sleep_checkbox)
        system_group.setLayout(system_layout)
        main_layout.addWidget(system_group)

        # --- 网络设置 ---
        network_group = QGroupBox("网络设置")
        network_layout = QFormLayout()

        self.proxy_checkbox = QCheckBox("使用系统代理")
        self.proxy_checkbox.setChecked(True)
        self.proxy_checkbox.setToolTip("启用后，程序将使用系统设置的代理服务器进行网络请求。")

        network_layout.addRow(self.proxy_checkbox)
        network_group.setLayout(network_layout)
        main_layout.addWidget(network_group)

        # 添加伸缩项以推送内容到顶部
        main_layout.addStretch()

        # 底部提示
        info_label = QLabel("ℹ️ 提示：凭证将在关闭时保存以供下次使用。")
        info_label.setStyleSheet("color: gray; font-size: 12px;")
        main_layout.addWidget(info_label)

        self.setLayout(main_layout)

    def _init_bindings(self) -> None:
        """将 UI 控件与全局状态 (AppState) 进行双向绑定"""
        # 普通属性，实时更新
        UIBinder.bind(self.sessdata_input, self.state, "sessdata", realtime=True)
        UIBinder.bind(self.bili_jct_input, self.state, "bili_jct", realtime=True)

        # 清空旧绑定，绑定 SenderConfig
        UIBinder.bind(self.prevent_sleep_checkbox, self.state.sender_config, "prevent_sleep", clear_old=True)
        UIBinder.bind(self.proxy_checkbox, self.state.sender_config, "use_system_proxy", clear_old=True)

        # 不清空，叠加绑定 MonitorConfig
        UIBinder.bind(self.prevent_sleep_checkbox, self.state.monitor_config, "prevent_sleep", clear_old=False)
        UIBinder.bind(self.proxy_checkbox, self.state.monitor_config, "use_system_proxy", clear_old=False)

    @Slot()
    def _open_qr_login(self):
        proxy = self.state.sender_config.use_system_proxy
        dialog = QRLoginDialog(proxy, self)

        # 阻塞等待弹窗返回。如果返回 Accepted，说明扫码成功
        if dialog.exec() == QDialog.DialogCode.Accepted:
            cookies = dialog.cookies
            sessdata = cookies.get('SESSDATA', '')
            bili_jct = cookies.get('bili_jct', '')

            if sessdata and bili_jct:
                self.sessdata_input.setText(sessdata)
                self.bili_jct_input.setText(bili_jct)

    # region 账号管理

    def set_current_profile(self, profile: UserProfile):
        """由 MainWindow 调用，传入当前登录的用户信息"""
        self._current_profile = profile

    @Slot()
    def _save_current_account(self):
        """保存当前凭证为新账号"""
        sessdata = self.state.sessdata.strip()
        bili_jct = self.state.bili_jct.strip()
        if not sessdata or not bili_jct:
            return

        profile = self._current_profile
        uid = profile.uid if profile and profile.is_login else 0
        name = profile.username if profile and profile.is_login else ""

        # 检查是否已存在同 uid 账号
        for acc in self.state.saved_accounts:
            if acc.uid == uid and uid != 0:
                # 更新已有账号的凭证
                acc.sessdata = sessdata
                acc.bili_jct = bili_jct
                self._refresh_account_list()
                return

        # 新增
        self.state.saved_accounts.append(AccountCredential(
            uid=uid, name=name, sessdata=sessdata, bili_jct=bili_jct
        ))
        self._refresh_account_list()

    @Slot()
    def _delete_selected_account(self):
        """删除选中的账号"""
        row = self.account_list.currentRow()
        if row < 0 or row >= len(self.state.saved_accounts):
            return
        self.state.saved_accounts.pop(row)
        self._refresh_account_list()

    @Slot(int)
    def _on_account_selected(self, row: int):
        """点击账号列表项：切换到该账号"""
        self.btn_delete_account.setEnabled(row >= 0)
        if row < 0 or row >= len(self.state.saved_accounts):
            return
        acc = self.state.saved_accounts[row]
        if acc.sessdata == self.state.sessdata and acc.bili_jct == self.state.bili_jct:
            return  # 已经是当前账号
        self.state.sessdata = acc.sessdata
        self.state.bili_jct = acc.bili_jct
        self.state.active_account_uid = acc.uid

    def _refresh_account_list(self):
        """刷新账号列表显示"""
        self.account_list.clear()
        for acc in self.state.saved_accounts:
            label = (acc.name or f"UID:{acc.uid}") if acc.uid else "(未命名)"
            if acc.uid == self.state.active_account_uid:
                label += "  ← 当前"
            self.account_list.addItem(label)

    # endregion