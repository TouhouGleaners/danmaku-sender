from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QLineEdit,
    QCheckBox, QGroupBox
)
from PySide6.QtCore import Qt

from .framework.binder import UIBinder

from ..core.state import AppState


class SettingsTab(QWidget):
    def __init__(self):
        super().__init__()

        self._state: AppState | None = None
        self._create_ui()

    def _create_ui(self):
        # 主布局 - 垂直布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # --- 身份凭证 ---
        auth_group = QGroupBox("身份凭证 (Cookie)")
        auth_layout = QFormLayout()
        auth_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

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

    def bind_state(self, state: AppState) -> None:
        """将 UI 控件与全局状态 (AppState) 进行双向绑定"""
        if self._state is state:
            return
            
        self._state = state

        # 普通属性，实时更新
        UIBinder.bind(self.sessdata_input, state, "sessdata", realtime=True)
        UIBinder.bind(self.bili_jct_input, state, "bili_jct", realtime=True)

        # 清空旧绑定，绑定 SenderConfig
        UIBinder.bind(self.prevent_sleep_checkbox, state.sender_config, "prevent_sleep", clear_old=True)
        UIBinder.bind(self.proxy_checkbox, state.sender_config, "use_system_proxy", clear_old=True)

        # 不清空，叠加绑定 MonitorConfig
        UIBinder.bind(self.prevent_sleep_checkbox, state.monitor_config, "prevent_sleep", clear_old=False)
        UIBinder.bind(self.proxy_checkbox, state.monitor_config, "use_system_proxy", clear_old=False)