import re
import logging
from typing import cast

import qrcode
from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QTextBrowser, QPushButton, QLabel
)
from PIL import Image

from .controllers.auth_controller import AuthController
from ..config.app_config import AppInfo, Links
from ..utils.path_utils import get_assets_path


logger = logging.getLogger("App.System.UI.Dialog")


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


class QRLoginDialog(QDialog):
    """扫码登录弹窗"""
    def __init__(self, use_system_proxy: bool, parent=None):
        super().__init__(parent)
        self.use_system_proxy = use_system_proxy
        self.cookies = {}  # 存放获取到的 Cookie

        self.auth_controller = AuthController(self)

        self._create_ui()
        self._connect_signals()

        self.auth_controller.start_qr_login(self.use_system_proxy)  # 对话框开启时直接启动业务逻辑

    def _create_ui(self):
        self.setWindowTitle("扫码登录")
        self.setFixedSize(300, 350)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.CustomizeWindowHint
        )

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(15)

        # 状态文案
        self.status_label = QLabel("正在向B站申请二维码...")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2c3e50;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # 二维码图片框
        self.qr_label = QLabel()
        self.qr_label.setFixedSize(200, 200)
        self.qr_label.setStyleSheet("background-color: #f8f9fa; border-radius: 8px;")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.qr_label)

        layout.addStretch()

        # 取消按钮
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedWidth(120)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self.cancel_btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def _connect_signals(self):
        # AuthController
        self.auth_controller.qrReady.connect(self._render_qr_code)
        self.auth_controller.qrStatusUpdated.connect(self.status_label.setText)
        self.auth_controller.qrLoginSucceeded.connect(self._on_login_succeeded)
        self.auth_controller.qrLoginFailed.connect(self._on_login_failed)

    def _render_qr_code(self, url: str):
        """将 URL 转换为 Qt 图像"""
        try:
            # 生成 PIL 图像
            qr = qrcode.QRCode(box_size=6, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            pil_img = cast(Image.Image, qr.make_image(fill_color="black", back_color="white")).convert("RGB")

            # 将 PIL 图像的二进制流转换为 QImage
            data = pil_img.tobytes("raw", "RGB")
            qimage = QImage(data, pil_img.width, pil_img.height, pil_img.width * 3, QImage.Format.Format_RGB888)

            # 设置到 UI
            pixmap = QPixmap.fromImage(qimage)
            pixmap = pixmap.scaled(
                self.qr_label.width(),
                self.qr_label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.qr_label.setPixmap(pixmap)
        except Exception as e:
            self.status_label.setText("二维码渲染失败")
            self.status_label.setStyleSheet("color: #e74c3c;")


    # region Slots

    @Slot(dict)
    def _on_login_succeeded(self, cookies: dict):
        """登录成功，保存数据并关闭窗口"""
        self.cookies = cookies
        self.accept()  # 触发 Accepted 信号，关闭弹窗

    @Slot(str)
    def _on_login_failed(self, error_msg: str):
        self.status_label.setText(error_msg)
        self.status_label.setStyleSheet("color: #e74c3c;")

    # endregion


    def done(self, r):
        """对话框清理"""
        if hasattr(self, 'auth_controller'):
            self.auth_controller.stop_qr_login()
        super().done(r)