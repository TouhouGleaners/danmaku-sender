from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QCheckBox, QGroupBox
)
from PySide6.QtCore import Qt

from .framework.binder import UIBinder

from ..core.state import AppState


class SettingsPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()

        self.state = state
        self._create_ui()

    def _create_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

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

        main_layout.addStretch()

        info_label = QLabel("💡 账号管理请点击左上角头像区域。")
        info_label.setStyleSheet("color: gray; font-size: 12px;")
        main_layout.addWidget(info_label)

        self.setLayout(main_layout)

    def init_bindings(self) -> None:
        """将 UI 控件与全局状态 (AppState) 进行双向绑定"""
        UIBinder.bind(self.prevent_sleep_checkbox, self.state.sender_config, "prevent_sleep", clear_old=True)
        UIBinder.bind(self.proxy_checkbox, self.state.sender_config, "use_system_proxy", clear_old=True)

        UIBinder.bind(self.prevent_sleep_checkbox, self.state.monitor_config, "prevent_sleep", clear_old=False)
        UIBinder.bind(self.proxy_checkbox, self.state.monitor_config, "use_system_proxy", clear_old=False)
