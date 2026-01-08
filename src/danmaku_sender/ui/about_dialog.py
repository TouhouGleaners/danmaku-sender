from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont

from ..config.app_config import AppInfo, Links
from ..config.app_content import AboutText


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"关于 {AppInfo.NAME}")
        self.setFixedSize(400, 300)
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)

        # 标题
        title = QLabel(AboutText.TOP)
        font = QFont()
        font.setBold(True)
        font.setPointSize(14)
        title.setFont(font)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # 版本和作者
        layout.addWidget(QLabel(f"版本: {AppInfo.VERSION}", alignment=Qt.AlignCenter))
        layout.addWidget(QLabel(AboutText.AUTHOR, alignment=Qt.AlignCenter))

        # GitHub 链接
        layout.addSpacing(10)
        layout.addWidget(QLabel("GitHub 仓库:", alignment=Qt.AlignCenter))
        
        link_btn = QPushButton(Links.GITHUB_REPO)
        link_btn.setCursor(Qt.PointingHandCursor)
        # 超链接样式
        link_btn.setStyleSheet("background: transparent; color: blue; border: none; text-decoration: underline;")
        link_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(Links.GITHUB_REPO)))
        layout.addWidget(link_btn)

        # 反馈提示
        layout.addSpacing(10)
        feedback_label = QLabel(AboutText.FEEDBACK)
        feedback_label.setAlignment(Qt.AlignCenter)
        feedback_label.setWordWrap(True)
        layout.addWidget(feedback_label)

        # Issue 链接
        issue_btn = QPushButton(AboutText.ISSUE_LINK_LABEL)
        issue_btn.setCursor(Qt.PointingHandCursor)
        issue_btn.setStyleSheet("background: transparent; color: blue; border: none;")
        issue_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(Links.GITHUB_ISSUES)))
        layout.addWidget(issue_btn)

        layout.addStretch()
        self.setLayout(layout)