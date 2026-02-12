import re
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QTextBrowser, QPushButton, QLabel
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices

from ..config.app_config import AppInfo, Links
from ..utils.resource_utils import get_assets_path


logger = logging.getLogger("HelpDialog")


class MarkdownBrowser(QTextBrowser):
    """专门用于显示 Markdown 的浏览器控件"""
    def __init__(self, doc_name: str):
        super().__init__()
        self.setOpenExternalLinks(True)
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.setStyleSheet("padding: 1px;") 
        
        md_path = get_assets_path() / "docs" / f"{doc_name}.md"
        if md_path.exists():
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    self.setMarkdown(f.read())
            except Exception as e:
                logger.error(f"加载帮助文档失败 [{md_path}]: {e}", exc_info=True)
                self._show_error_placeholder("无法加载文档内容，请检查日志。")
        else:
            logger.warning(f"帮助文档缺失: {md_path}")
            self._show_error_placeholder("该模块暂无帮助文档。")

    def _show_error_placeholder(self, message: str):
        """显示一个居中的灰色提示文字"""
        self.setHtml(f"""
            <div style='text-align: center; margin-top: 50px; color: #888888;'>
                <h3>⚠️</h3>
                <p>{message}</p>
            </div>
        """)


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("使用说明")
        self.resize(600, 500)
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()

        self.tabs.addTab(MarkdownBrowser("sender"), "弹幕发射器")
        self.tabs.addTab(MarkdownBrowser("validator"), "弹幕校验器")
        self.tabs.addTab(MarkdownBrowser("monitor"), "弹幕监视器")

        layout.addWidget(self.tabs)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)
        

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"关于")
        self.setFixedSize(400, 300)
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)
        
        # 标题
        title = QLabel(AppInfo.NAME)
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #fb7299;")
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)

        # 版本与作者
        layout.addWidget(QLabel(f"v{AppInfo.VERSION}"), alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(QLabel(f"By {AppInfo.AUTHOR}"), alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(15)

        # 链接区域
        repo_btn = QPushButton("GitHub 仓库")
        repo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        repo_btn.setStyleSheet("color: #00a1d6; border: none; text-decoration: underline; background: transparent;")
        repo_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(Links.GITHUB_REPO)))
        layout.addWidget(repo_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # 反馈文案 (直接写在这里，修改看这里就行)
        feedback_text = (
            "如果您在使用过程中遇到任何问题或有改进建议，\n"
            "欢迎前往 GitHub Issues 页面提交反馈。"
        )
        feedback = QLabel(feedback_text)
        feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        feedback.setWordWrap(True)
        feedback.setStyleSheet("color: #666; font-size: 12px; margin: 10px;")
        layout.addWidget(feedback)

        # Issue 链接
        issue_btn = QPushButton(">>> 前往反馈页面 <<<")
        issue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        issue_btn.setStyleSheet("color: #00a1d6; border: none; background: transparent;")
        issue_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(Links.GITHUB_ISSUES)))
        layout.addWidget(issue_btn)

        layout.addStretch()
        
        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)


class UpdateDialog(QDialog):
    def __init__(self, version: str, notes: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"发现新版本 v{version}")
        self.resize(600, 450)

        self._create_ui(version, notes)

    def _create_ui(self, version, notes):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # --- Title ---
        title_label = QLabel(f"🎉 发现新版本: <b>{version}</b>")
        title_label.setStyleSheet("font-size: 16px; margin-bottom: 5px;")
        layout.addWidget(title_label)

        # --- Content ---
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)

        clean_notes = self._preprocess_markdown(notes)
        self.browser.setMarkdown(clean_notes)

        self.browser.setStyleSheet("""
            QTextBrowser {
                font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
                font-size: 10px;
                line-height: 1.6;
                color: #24292e;
                background-color: #ffffff;
                border: 1px solid #e1e4e8;
                border-radius: 6px;
                padding: 20px;
            }
        """)
        layout.addWidget(self.browser)

        # --- Button ---
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.btn_ignore = QPushButton("稍后")
        self.btn_ignore.clicked.connect(self.reject)

        self.btn_update = QPushButton("前往下载")
        self.btn_update.setStyleSheet("""
            QPushButton {
                background-color: #00a1d6;
                color: white;
                font-weight: bold;
                padding: 6px 15px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #00b5e5; }
        """)
        self.btn_update.clicked.connect(self.accept)

        btn_box.addWidget(self.btn_ignore)
        btn_box.addWidget(self.btn_update)

        layout.addLayout(btn_box)

    def _preprocess_markdown(self, text: str) -> str:
        """清洗 GitHub Markdown，使其适配 Qt 的富文本引擎"""
        if not text:
            return ""

        # 处理 <summary>：替换为 H4 标题或粗体，并强制换行
        text = re.sub(r'<summary>\s*(.*?)\s*</summary>', r'\n#### \1\n', text, flags=re.IGNORECASE)
        text = text.replace('<details>', '').replace('</details>', '')

        # 修复 GitHub Compare 链接 (包含 ... 的链接)
        text = re.sub(
            r'\*\*Full Changelog\*\*: (https://github\.com/\S+/compare/(\S+))', 
            r'**Full Changelog**: [👉 查看 \2 变更对比](\1)', 
            text
        )

        return text