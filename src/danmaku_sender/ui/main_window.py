import logging

from PySide6.QtWidgets import QMainWindow, QTabWidget, QMessageBox
from PySide6.QtGui import QCloseEvent
from PySide6.QtCore import Qt

from .sender_tab import SenderTab
from .settings_tab import SettingsTab
from .monitor_tab import MonitorTab
from .validator_tab import ValidatorTab

from ..core.state import AppState
from ..utils.credential_manager import load_credentials, save_credentials


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("B站弹幕补档工具 v2.0-dev")
        self.resize(750, 650)

        # 核心状态
        self.state = AppState()
        self.logger = logging.getLogger("MainWindow")

        # 中央部件
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # 初始化各页面
        self.init_tabs()

        # 从磁盘中加载凭证
        self._load_initial_credentials()

        # 绑定 State 到各个 Tab
        self.bind_state_to_tabs()

    def init_tabs(self):
        self.tab_settings = SettingsTab()
        self.tab_sender = SenderTab()
        self.tab_validator = ValidatorTab()
        self.tab_monitor = MonitorTab()

        # 添加至选项卡
        self.tabs.addTab(self.tab_settings, "全局设置")
        self.tabs.addTab(self.tab_sender, "弹幕发射器")
        self.tabs.addTab(self.tab_validator, "弹幕校验器")
        self.tabs.addTab(self.tab_monitor, "弹幕监视器")

        # 默认选中发射器
        self.tabs.setCurrentWidget(self.tab_sender)

    def _load_initial_credentials(self):
        """程序启动时，从 Keyring 读取加密的凭证并填充到设置页面。"""
        try:
            credentials = load_credentials()
            self.state.sessdata = credentials.get("SESSDATA", "")
            self.state.bili_jct = credentials.get("BILI_JCT", "")
            self.logger.info("成功加载存储的凭证。")
        except Exception as e:
            self.logger.warning(f"加载凭证失败: {e}")

    def bind_state_to_tabs(self):
        """将 AppState 绑定到各个 Tab 页面。"""
        self.tab_settings.bind_state(self.state)
        self.tab_sender.bind_state(self.state)
        # self.tab_validator.bind_state(self.state)
        self.tab_monitor.bind_state(self.state)

        self.state.log_message.connect(self._on_log_recevied)

    def _on_log_recevied(self, message: str):
        """将日志输出到当前活动的或相关的日志框"""
        self.tab_sender.append_log(message)
        self.tab_monitor.append_log(message)

    def closeEvent(self, event: QCloseEvent):
        """
        窗口关闭事件：
        PySide6 退出时会自动触发此方法。
        """
        try:
            credentials_to_save = {
                'SESSDATA': self.state.sessdata,
                'BILI_JCT': self.state.bili_jct
            }
            save_credentials(credentials_to_save)
            self.logger.info("凭证已加密保存。")
        except Exception as e:
            self.logger.error(f"保存凭证失败: {e}")
            QMessageBox.warning(self, "保存失败", f"无法保存凭证：\n{e}")

        # 接受关闭事件，允许窗口关闭
        super().closeEvent(event)