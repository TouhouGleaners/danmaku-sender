import re
import logging
from typing import cast

import qrcode
from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QScrollArea,
    QTextBrowser, QPushButton, QLabel, QFrame, QLineEdit,
    QFormLayout, QMessageBox, QWidget
)
from PIL import Image

from .controllers.auth_controller import AuthController
from .framework.style_loader import get_svg_icon
from .framework.image_processor import QtImageProcessor

from ..core.models.common import AuthCookies
from ..core.models.user import UserProfile
from ..core.models.account import AccountCredential
from ..core.state import AppState
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
        self.cookies: AuthCookies = {'SESSDATA': '', 'bili_jct': ''}

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

    @Slot(str)
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
    def _on_login_succeeded(self, cookies: AuthCookies):
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


# ============================================================
# 账号管理弹窗
# ============================================================

class _AccountCard(QFrame):
    """单个账号的展示卡片"""

    clicked = Signal(int)  # 携带 uid

    def __init__(self, account: AccountCredential, avatar_bytes: bytes = b"",
                 is_active: bool = False, parent=None):
        super().__init__(parent)
        self._uid = account.uid
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(56)
        self.setObjectName("accountCardActive" if is_active else "accountCard")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        # 头像
        avatar_label = QLabel()
        avatar_label.setFixedSize(36, 36)
        avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if avatar_bytes:
            pixmap = QtImageProcessor.make_circular_pixmap(avatar_bytes, 36)
            if not pixmap.isNull():
                avatar_label.setPixmap(pixmap)
            else:
                avatar_label.setText("👤")
        else:
            avatar_label.setText("👤")
            avatar_label.setStyleSheet("font-size: 20px;")
        layout.addWidget(avatar_label)

        # 信息区
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_text = account.name or f"UID:{account.uid}" if account.uid else "(未命名)"
        name_label = QLabel(name_text)
        name_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        info_layout.addWidget(name_label)

        if account.uid:
            uid_label = QLabel(f"UID: {account.uid}")
            uid_label.setStyleSheet("color: gray; font-size: 11px;")
            info_layout.addWidget(uid_label)

        layout.addLayout(info_layout, 1)

        # 当前账号标记
        if is_active:
            check_label = QLabel("✓")
            check_label.setStyleSheet("color: #4CAF50; font-size: 18px; font-weight: bold;")
            layout.addWidget(check_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._uid)
        super().mousePressEvent(event)


class AccountDialog(QDialog):
    """账号管理弹窗"""

    def __init__(self, state: AppState, current_profile: UserProfile | None, parent=None):
        super().__init__(parent)
        self.state = state
        self._profile = current_profile
        self._avatar_cache: dict[int, bytes] = {}  # uid -> avatar_bytes
        self.setMinimumWidth(360)
        self.setMaximumWidth(420)
        self.setWindowTitle("账号管理")
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.CustomizeWindowHint
        )

        self._create_ui()
        self._populate()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 当前账号区
        self._current_frame = QFrame()
        self._current_frame.setObjectName("accountCardActive")
        self._current_layout = QVBoxLayout(self._current_frame)
        self._current_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._current_frame)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e0e0e0;")
        layout.addWidget(sep)

        # 其他账号标题
        if self.state.saved_accounts:
            self._others_label = QLabel("已保存的账号")
            self._others_label.setStyleSheet("color: gray; font-size: 12px;")
            layout.addWidget(self._others_label)

        # 其他账号列表（滚动区域）
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setMaximumHeight(240)
        self._scroll_container = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_container)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(4)
        self._scroll.setWidget(self._scroll_container)
        layout.addWidget(self._scroll)

        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_add_qr = QPushButton("扫码添加")
        self.btn_add_qr.setIcon(get_svg_icon("qr_scan.svg"))
        self.btn_add_qr.clicked.connect(self._add_qr)

        self.btn_add_manual = QPushButton("手动输入")
        self.btn_add_manual.clicked.connect(self._add_manual)

        btn_layout.addWidget(self.btn_add_qr)
        btn_layout.addWidget(self.btn_add_manual)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 底部操作
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(8)

        self.btn_logout = QPushButton("退出当前账号")
        self.btn_logout.setStyleSheet("color: #e74c3c;")
        self.btn_logout.clicked.connect(self._logout)

        self.btn_remove = QPushButton("移除当前账号")
        self.btn_remove.setStyleSheet("color: #e74c3c;")
        self.btn_remove.clicked.connect(self._remove)

        bottom_layout.addWidget(self.btn_logout)
        bottom_layout.addWidget(self.btn_remove)
        bottom_layout.addStretch()
        layout.addLayout(bottom_layout)

    def _populate(self):
        """填充账号列表"""
        active_uid = self.state.active_account_uid

        # 当前账号
        current_acc = self._find_account(active_uid)
        if current_acc:
            avatar_bytes = self._get_avatar_for_current()
            card = _AccountCard(current_acc, avatar_bytes, is_active=True)
            self._current_layout.addWidget(card)
        else:
            # 没有保存的账号但有凭证（手动输入的）
            if self.state.sessdata:
                placeholder = AccountCredential(
                    sessdata=self.state.sessdata, bili_jct=self.state.bili_jct
                )
                card = _AccountCard(placeholder, is_active=True)
                self._current_layout.addWidget(card)

        # 其他账号
        for acc in self.state.saved_accounts:
            if acc.uid == active_uid:
                continue
            card = _AccountCard(acc, is_active=False)
            card.clicked.connect(self._switch_to)
            self._scroll_layout.addWidget(card)

        self._scroll_layout.addStretch()

        # 更新按钮状态
        has_current = bool(self.state.sessdata)
        self.btn_logout.setEnabled(has_current)
        self.btn_remove.setEnabled(active_uid in {a.uid for a in self.state.saved_accounts})

    def _find_account(self, uid: int) -> AccountCredential | None:
        for acc in self.state.saved_accounts:
            if acc.uid == uid:
                return acc
        return None

    def _get_avatar_for_current(self) -> bytes:
        """获取当前账号的头像（优先用 profile）"""
        if self._profile and self._profile.avatar_bytes:
            return self._profile.avatar_bytes
        return b""

    @Slot(int)
    def _switch_to(self, uid: int):
        """切换到指定账号"""
        acc = self._find_account(uid)
        if not acc:
            return
        self.state.sessdata = acc.sessdata
        self.state.bili_jct = acc.bili_jct
        self.state.active_account_uid = uid
        self.accept()

    @Slot()
    def _add_qr(self):
        """扫码添加新账号"""
        proxy = self.state.sender_config.use_system_proxy
        dialog = QRLoginDialog(proxy, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            cookies = dialog.cookies
            sessdata = cookies.get('SESSDATA', '')
            bili_jct = cookies.get('bili_jct', '')
            if sessdata and bili_jct:
                # 写入 AppState，触发 profile 获取
                self.state.sessdata = sessdata
                self.state.bili_jct = bili_jct
                # 先以 uid=0 暂存，profile 获取后由 MainWindow 更新 uid
                self.state.saved_accounts.append(AccountCredential(
                    sessdata=sessdata, bili_jct=bili_jct
                ))
                self.accept()

    @Slot()
    def _add_manual(self):
        """手动输入凭证"""
        dialog = ManualLoginDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            sessdata, bili_jct = dialog.credentials
            self.state.sessdata = sessdata
            self.state.bili_jct = bili_jct
            self.state.saved_accounts.append(AccountCredential(
                sessdata=sessdata, bili_jct=bili_jct
            ))
            self.accept()

    @Slot()
    def _logout(self):
        """退出当前账号（清除凭证，保留账号条目）"""
        reply = QMessageBox.question(
            self, "退出登录",
            "确定要退出当前账号吗？\n退出后需要重新扫码或手动输入才能使用。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.state.sessdata = ""
            self.state.bili_jct = ""
            self.state.active_account_uid = 0
            self.accept()

    @Slot()
    def _remove(self):
        """移除当前账号（从保存列表中删除）"""
        uid = self.state.active_account_uid
        acc = self._find_account(uid)
        name = acc.name if acc else "当前账号"
        reply = QMessageBox.question(
            self, "移除账号",
            f"确定要移除账号「{name}」吗？\n移除后需要重新添加才能使用。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.state.saved_accounts = [
                a for a in self.state.saved_accounts if a.uid != uid
            ]
            self.state.sessdata = ""
            self.state.bili_jct = ""
            self.state.active_account_uid = 0
            self.accept()


class ManualLoginDialog(QDialog):
    """手动输入凭证弹窗"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.credentials: tuple[str, str] = ("", "")
        self.setWindowTitle("手动输入凭证")
        self.setFixedWidth(380)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.CustomizeWindowHint
        )

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.se_input = QLineEdit()
        self.se_input.setPlaceholderText("请输入 SESSDATA")
        self.se_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.jct_input = QLineEdit()
        self.jct_input.setPlaceholderText("请输入 bili_jct")
        self.jct_input.setEchoMode(QLineEdit.EchoMode.Password)

        form.addRow("SESSDATA:", self.se_input)
        form.addRow("bili_jct:", self.jct_input)
        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self._on_accept)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def _on_accept(self):
        se = self.se_input.text().strip()
        jct = self.jct_input.text().strip()
        if not se or not jct:
            QMessageBox.warning(self, "输入不完整", "SESSDATA 和 bili_jct 均不能为空。")
            return
        self.credentials = (se, jct)
        self.accept()