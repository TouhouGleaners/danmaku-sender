from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QTabWidget, QTextEdit, 
    QPushButton, QHBoxLayout
)
from ..config.app_content import HelpText


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("使用说明")
        self.resize(700, 600)
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout()
        
        tabs = QTabWidget()
        tabs.addTab(self._create_text_tab(HelpText.SENDER), "弹幕发射器")
        tabs.addTab(self._create_text_tab(HelpText.VALIDATOR), "弹幕校验器")
        tabs.addTab(self._create_text_tab(HelpText.MONITOR), "弹幕监视器")
        
        layout.addWidget(tabs)
        
        # 底部关闭按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def _create_text_tab(self, content):
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(content)
        font = text_edit.font()
        font.setPointSize(10)
        text_edit.setFont(font)
        return text_edit