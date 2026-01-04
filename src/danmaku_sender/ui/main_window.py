from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

from .sender_tab import SenderTab
from .settings_tab import SettingsTab
from .monitor_tab import MonitorTab
from .validator_tab import ValidatorTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("B站弹幕补档工具 v2.0-dev")
        self.resize(900, 700)

        # 中央部件
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # 初始化各页面
        self.init_tabs()

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