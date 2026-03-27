import logging
from pathlib import Path
from platformdirs import user_data_dir

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QMessageBox, QHBoxLayout, QVBoxLayout, QFrame,
    QListWidget, QListWidgetItem, QStackedWidget, QLabel
)
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtCore import Qt, QUrl, QTimer, QSize

from .controllers.auth_controller import AuthController, UserProfile
from .controllers.system_controller import SystemController
from .framework.image_processor import QtImageProcessor
from .sender_page import SenderPage
from .settings_page import SettingsPage
from .monitor_page import MonitorPage
from .editor_page import EditorPage
from .dialogs import AboutDialog, HelpDialog, UpdateDialog
from .history_page import HistoryPage

from ..config.app_config import AppInfo, UI
from ..core.state import AppState
from ..utils.log_utils import GuiLoggingHandler
from ..utils.credential_manager import load_credentials, save_credentials
from ..utils.config_manager import load_app_config, save_app_config
from ..utils.resource_utils import load_stylesheet, get_svg_icon


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(UI.MAIN_WINDOW_TITLE)
        self.resize(900, 680)

        # 核心状态
        self.state = AppState()
        self.auth_ctrl = AuthController(self)
        self.sys_ctrl = SystemController(self)
        self._log_signals_connected = False
        self.logger = logging.getLogger("App.System.UI.Main")

        self._create_ui()
        self.init_pages()
        self._setup_system_signals()
        self.create_menu_bar()

        # 从磁盘中加载凭证
        self._load_initial_credentials()
        load_app_config(self.state)

        # 绑定逻辑信号
        self.bind_state_to_pages()
        self._setup_user_logic()
        load_stylesheet()

        # 存储帮助窗口的引用，防止被垃圾回收
        self._help_dialog = None

        QTimer.singleShot(1000, lambda: self.run_update_check(is_manual=False))

    def _create_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # 主布局: 水平分栏
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # --- 左侧侧边栏容器 ---
        self.sidebar_frame = QFrame()
        self.sidebar_frame.setObjectName("sidebarFrame")
        self.sidebar_frame.setFixedWidth(160)

        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(0, 0, 0, 10)
        sidebar_layout.setSpacing(0)

        # 用户状态页眉
        self.user_widget = QFrame()
        self.user_widget.setObjectName("userWidget")
        self.user_widget.setFixedHeight(65)
        user_layout = QHBoxLayout(self.user_widget)
        user_layout.setContentsMargins(15, 0, 10, 0)
        user_layout.setSpacing(10)

        self.avatar_label = QLabel()
        self.avatar_label.setObjectName("avatarLabel")
        self.avatar_label.setFixedSize(36, 36)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        default_icon = get_svg_icon("default_avatar.svg")
        pixmap = default_icon.pixmap(36, 36)
        self.avatar_label.setPixmap(pixmap)

        self.username_label = QLabel("未登录")
        self.username_label.setObjectName("usernameLabel")
        self.username_label.setStyleSheet("font-weight: bold; font-size: 13px;")

        user_layout.addWidget(self.avatar_label)
        user_layout.addWidget(self.username_label)
        user_layout.addStretch()

        # 导航列表
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setIconSize(QSize(20, 20))
        self.sidebar.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # 组装侧边栏
        sidebar_layout.addWidget(self.user_widget)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #f1f2f3; margin: 0 10px;")
        sidebar_layout.addWidget(line)
        sidebar_layout.addWidget(self.sidebar)

        # --- 右侧内容容器 ---
        self.content_stack = QStackedWidget()

        self.main_layout.addWidget(self.sidebar_frame)
        self.main_layout.addWidget(self.content_stack)

    def init_pages(self):
        """初始化页面并绑定导航"""
        self.page_settings = SettingsPage()
        self.page_sender = SenderPage()
        self.page_editor = EditorPage()
        self.page_monitor = MonitorPage()
        self.page_history = HistoryPage()

        # 定义页面列表
        pages = [
            ("全局设置", self.page_settings, "settings.svg"),
            ("弹幕发射器", self.page_sender, "send.svg"),
            ("弹幕编辑器", self.page_editor, "edit.svg"),
            ("弹幕监视器", self.page_monitor, "monitor.svg"),
            ("弹幕历史记录", self.page_history, "history.svg"),
        ]

        for title, widget, icon_name in pages:
            item = QListWidgetItem(get_svg_icon(icon_name), f"{title}")
            self.sidebar.addItem(item)
            self.content_stack.addWidget(widget)

        self.sidebar.currentRowChanged.connect(self.content_stack.setCurrentIndex)
        self.sidebar.setCurrentRow(1)

        # 用户页眉点击跳转到设置页
        self.user_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        self.user_widget.mousePressEvent = lambda e: self.sidebar.setCurrentRow(0)

    def _setup_user_logic(self):
        """用户信息获取逻辑"""
        self.state.credentials_changed.connect(self.request_user_info_refresh)
        self.auth_ctrl.user_profile_ready.connect(self._on_user_profile_updated)
        QTimer.singleShot(500, self.request_user_info_refresh)

        self.state.editor_dirty_changed.connect(self._refresh_sidebar_badges)
        self.state.sender_active_changed.connect(self._refresh_sidebar_badges)

    def _refresh_sidebar_badges(self, _=None):
        """核心视觉逻辑：动态刷新侧边栏项目的文字后缀"""
        # 弹幕发射器
        sender_item = self.sidebar.item(1)
        if sender_item:
            if self.state.sender_is_active:
                sender_item.setText("弹幕发射器 ▶")
            else:
                sender_item.setText("弹幕发射器")

        # 弹幕编辑器
        editor_item = self.sidebar.item(2)
        if editor_item:
            if self.state.editor_is_dirty:
                editor_item.setText("弹幕编辑器 •")
            else:
                editor_item.setText("弹幕编辑器")

    def request_user_info_refresh(self):
        """发起异步请求刷新用户信息"""
        self.auth_ctrl.refresh_user_info(self.state.get_api_auth())

    def _refresh_default_avatar(self):
        """通用方法：渲染高清的默认头像"""
        dpr = self.devicePixelRatioF()
        icon = get_svg_icon("default_avatar.svg")
        physical_size = QSize(int(36 * dpr), int(36 * dpr))
        pixmap = icon.pixmap(physical_size)
        pixmap.setDevicePixelRatio(dpr)
        self.avatar_label.setPixmap(pixmap)

    def _on_user_profile_updated(self, profile: UserProfile):
        """同步更新 UI"""
        # 更新文字
        self.username_label.setText(profile.username)

        dpr = self.devicePixelRatioF()

        # 更新头像
        if profile.is_login and profile.avatar_bytes:
            dpr = self.devicePixelRatioF()
            # 这里的 image_processor 内部也需要确保 physical_size = int(size * dpr)
            pixmap = QtImageProcessor.make_circular_pixmap(profile.avatar_bytes, 36, dpr)
            if not pixmap.isNull():
                self.avatar_label.setPixmap(pixmap)
                return

        # 未登录或无头像
        self._refresh_default_avatar()

    def create_menu_bar(self):
        menu_bar = self.menuBar()

        # --- 文件菜单 ---
        file_menu = menu_bar.addMenu("文件")

        open_log_action = QAction("打开日志文件夹", self)
        open_log_action.triggered.connect(self.open_log_folder)
        file_menu.addAction(open_log_action)

        file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # --- 帮助菜单 ---
        help_menu = menu_bar.addMenu("帮助")

        usage_action = QAction("使用说明", self)
        usage_action.triggered.connect(self.show_help)
        help_menu.addAction(usage_action)

        help_menu.addSeparator()

        update_action = QAction("检查新版本", self)
        update_action.triggered.connect(lambda: self.run_update_check(is_manual=True))
        help_menu.addAction(update_action)

        help_menu.addSeparator()

        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def show_help(self):
        """显示非模态的帮助窗口"""
        if not self._help_dialog:
            self._help_dialog = HelpDialog()
            self._help_dialog.finished.connect(lambda *args: setattr(self, '_help_dialog', None))

        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    def show_about(self):
        AboutDialog(self).exec()

    def open_log_folder(self):
        log_dir = Path(user_data_dir(AppInfo.NAME_EN, AppInfo.AUTHOR)) / AppInfo.LOG_DIR_NAME
        if not log_dir.exists():
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "错误", f"无法创建日志目录：\n{e}")
                return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    def _load_initial_credentials(self):
        """程序启动时，从 Keyring 读取加密的凭证并填充到设置页面。"""
        try:
            credentials = load_credentials()
            self.state.sessdata = credentials.get("SESSDATA", "")
            self.state.bili_jct = credentials.get("BILI_JCT", "")
            self.logger.info("成功加载存储的凭证。")
        except Exception as e:
            self.logger.warning(f"加载凭证失败: {e}")

    def bind_state_to_pages(self):
        """绑定全局状态并配置日志路由"""
        # 页面数据绑定
        self.page_settings.bind_state(self.state)
        self.page_sender.bind_state(self.state)
        self.page_editor.bind_state(self.state)
        self.page_monitor.bind_state(self.state)
        self.page_history.bind_state(self.state)

        # 日志分流：信号 -> Tab 接口
        if self._log_signals_connected:
            self.state.sender_log_received.disconnect(self.page_sender.append_log)
            self.state.monitor_log_received.disconnect(self.page_monitor.append_log)

        self.state.sender_log_received.connect(self.page_sender.append_log)
        self.state.monitor_log_received.connect(self.page_monitor.append_log)
        self._log_signals_connected = True

        # 信号接入：底层 Handler -> 信号发射
        self._setup_log_routing()

    def _setup_log_routing(self):
        """从根 Logger 查找 GuiLoggingHandler 并绑定信号。"""
        root_logger = logging.getLogger()
        gui_handler = None

        # 遍历所有挂载的处理器，找到 GUI 路由
        for h in root_logger.handlers:
            if isinstance(h, GuiLoggingHandler):
                gui_handler = h
                break

        if gui_handler:
            # 将 Handler 的回调指向 AppState 的信号
            gui_handler.sender_callback = self.state.sender_log_received.emit
            gui_handler.monitor_callback = self.state.monitor_log_received.emit
            self.logger.info("日志路由链路已接通。")
        else:
            self.logger.error("日志路由系统初始化失败：未找到 GuiLoggingHandler。")

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

        save_app_config(self.state)

        if self._help_dialog:
            self._help_dialog.close()

        # 接受关闭事件，允许窗口关闭
        super().closeEvent(event)

    def run_update_check(self, is_manual: bool = False):
        """启动更新检查"""
        self.sys_ctrl.check_for_updates(self.state.sender_config.use_system_proxy, is_manual)

    def _on_update_found(self, ver, notes, url):
        """发现新版本时的弹窗"""
        dialog = UpdateDialog(ver, notes, self)

        if dialog.exec():
            QDesktopServices.openUrl(QUrl(url))

    def _setup_system_signals(self):
        """连接系统信号"""
        self.sys_ctrl.update_found.connect(self._on_update_found)
        self.sys_ctrl.no_update.connect(lambda is_m:
            QMessageBox.information(self, "检查更新", "当前已是最新版本。") if is_m else None
        )
        self.sys_ctrl.check_failed.connect(lambda err, is_m:
            QMessageBox.warning(self, "检查更新失败", f"无法连接到更新服务器:\n{err}") if is_m else None
        )