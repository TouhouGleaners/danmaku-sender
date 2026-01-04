from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("B站弹幕补档工具 v2.0-dev")
        self.resize(900, 700)

        # 中央部件
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # 初始化各页面（占位
        self.init_tabs()

    def init_tabs(self):
        # 这里的 QWidget 以后会被替换成真正的 SenderTab, ValidatorTab 类
        self.tab_settings = QWidget()
        self.tab_sender = QWidget()
        self.tab_validator = QWidget()
        self.tab_monitor = QWidget()

        # 添加至选项卡
        self.tabs.addTab(self.tab_settings, "全局设置")
        self.tabs.addTab(self.tab_sender, "弹幕发射器")
        self.tabs.addTab(self.tab_validator, "弹幕校验器")
        self.tabs.addTab(self.tab_monitor, "弹幕监视器")

        # 默认选中发射器
        self.tabs.setCurrentWidget(self.tab_sender)

        # 占位内容
        self._add_placeholder_text(self.tab_sender, "发射器施工中...")

    def _add_placeholder_text(self, widget, text):
        """临时辅助函数：给空白页加个标签"""
        layout = QVBoxLayout()
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter) # 居中
        layout.addWidget(label)
        widget.setLayout(layout)