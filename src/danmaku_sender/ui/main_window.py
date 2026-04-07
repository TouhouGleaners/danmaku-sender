import logging
from pathlib import Path
from platformdirs import user_data_dir

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QMessageBox, QHBoxLayout, QVBoxLayout, QFrame, QApplication,
    QListWidget, QListWidgetItem, QStackedWidget, QLabel, QSystemTrayIcon, QMenu
)
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtCore import Qt, QUrl, QTimer, QSize, QEvent, Slot

from .controllers.auth_controller import AuthController, UserProfile
from .controllers.system_controller import SystemController
from .framework.image_processor import QtImageProcessor
from .framework.style_loader import load_stylesheet, get_svg_icon, get_app_icon
from .sender_page import SenderPage
from .settings_page import SettingsPage
from .monitor_page import MonitorPage
from .editor import EditorPage
from .dialogs import AboutDialog, HelpDialog, UpdateDialog
from .history_page import HistoryPage
from .theme_manager import ThemeManager

from ..config.app_config import AppInfo, UI
from ..core.state import AppState
from ..utils.log_utils import GuiLoggingHandler
from ..utils.credential_manager import load_credentials, save_credentials
from ..utils.config_manager import load_app_config, save_app_config


class MainWindow(QMainWindow):
    # region Lifecycle & Initialization
    def __init__(self):
        super().__init__()

        self.setWindowTitle(UI.MAIN_WINDOW_TITLE)
        self.resize(900, 680)

        ThemeManager.instance().init_theme()
        ThemeManager.instance().themeChanged.connect(self._on_theme_changed)

        # 核心状态
        self.state = AppState()
        self.auth_controller = AuthController(self)
        self.system_controller = SystemController(self)
        self.logger = logging.getLogger("App.System.UI.Main")
        self._log_signals_connected = False
        self._help_dialog = None  # 存储帮助窗口的引用，防止被垃圾回收

        # 运行时状态
        self._current_sender_progress = (0, 0)
        self._current_monitor_stats = {}

        # UI 初始化
        self._create_ui()
        self._init_pages()
        self._create_menu_bar()
        self._init_system_tray()

        # 数据与配置加载
        self._init_auth_system()
        self._load_initial_credentials()
        load_app_config(self.state)

        # 信号与状态绑定
        self._bind_state_to_pages()
        self._connect_global_signals()

        # 加载样式与后续任务
        load_stylesheet()
        QTimer.singleShot(1000, lambda: self._run_update_check(is_manual=False))

    def changeEvent(self, event: QEvent):
        """窗口状态变化: 最小化到托盘"""
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized():
                self.hide()
                self.tray_icon.showMessage(
                    AppInfo.NAME,
                    "程序已最小化到托盘，后台监视/发送任务将继续运行。",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000
                )
                event.accept()
                return
        super().changeEvent(event)

    def closeEvent(self, event: QCloseEvent):
        """窗口关闭事件: 保存配置与凭证"""
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

        super().closeEvent(event)

    # endregion
    # region UI Setup

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
        self._refresh_default_avatar()

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

    def _init_pages(self):
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

    def _create_menu_bar(self):
        menu_bar = self.menuBar()

        # --- 文件菜单 ---
        file_menu = menu_bar.addMenu("文件")

        open_log_action = QAction("打开日志文件夹", self)
        open_log_action.triggered.connect(self._open_log_folder)
        file_menu.addAction(open_log_action)

        file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # --- 帮助菜单 ---
        help_menu = menu_bar.addMenu("帮助")

        usage_action = QAction("使用说明", self)
        usage_action.triggered.connect(self._show_help)
        help_menu.addAction(usage_action)

        help_menu.addSeparator()

        update_action = QAction("检查新版本", self)
        update_action.triggered.connect(lambda: self._run_update_check(is_manual=True))
        help_menu.addAction(update_action)

        help_menu.addSeparator()

        about_action = QAction("关于", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _init_system_tray(self):
        """初始化系统托盘"""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(get_app_icon())

        # 托盘右键菜单
        tray_menu = QMenu(self)

        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self._show_from_tray)

        quit_action = QAction("完全退出", self)
        quit_action.triggered.connect(self._force_quit)

        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

        self._refresh_global_status()

    # endregion
    # region Data Binding & Signal

    def _init_auth_system(self):
        """专门用于初始化认证相关的防抖计时器与逻辑"""
        self._auth_debounce_timer = QTimer(self)
        self._auth_debounce_timer.setSingleShot(True)
        self._auth_debounce_timer.timeout.connect(self._do_user_info_refresh)

    def _load_initial_credentials(self):
        """加载本地加密凭证"""
        try:
            credentials = load_credentials()
            self.state.sessdata = credentials.get("SESSDATA", "")
            self.state.bili_jct = credentials.get("BILI_JCT", "")
            self.logger.info("成功加载存储的凭证。")
        except Exception as e:
            self.logger.warning(f"加载凭证失败: {e}")

    def _bind_state_to_pages(self):
        """绑定全局状态并配置日志路由"""
        # 页面数据绑定
        self.page_settings.bind_state(self.state)
        self.page_sender.bind_state(self.state)
        self.page_editor.bind_state(self.state)
        self.page_monitor.bind_state(self.state)
        self.page_history.bind_state(self.state)

        # 日志分流：信号 -> Tab 接口
        if self._log_signals_connected:
            self.state.senderLogReceived.disconnect(self.page_sender.append_log)
            self.state.monitorLogReceived.disconnect(self.page_monitor.append_log)

        self.state.senderLogReceived.connect(self.page_sender.append_log)
        self.state.monitorLogReceived.connect(self.page_monitor.append_log)
        self._log_signals_connected = True

        # 信号接入：底层 Handler -> 信号发射
        self._setup_log_routing()

    def _setup_log_routing(self):
        """配置 GuiLoggingHandler 路由"""
        root_logger = logging.getLogger()
        gui_handler = None

        # 遍历所有挂载的处理器，找到 GUI 路由
        for h in root_logger.handlers:
            if isinstance(h, GuiLoggingHandler):
                gui_handler = h
                break

        if gui_handler:
            # 将 Handler 的回调指向 AppState 的信号
            gui_handler.sender_callback = self.state.senderLogReceived.emit
            gui_handler.monitor_callback = self.state.monitorLogReceived.emit
            self.logger.info("日志路由链路已接通。")
        else:
            self.logger.error("日志路由系统初始化失败：未找到 GuiLoggingHandler。")

    def _connect_global_signals(self):
        """全局信号绑定"""
        # 用户认证与基础信息
        self.state.credentialsChanged.connect(self._request_user_info_refresh)
        self.auth_controller.userProfileReady.connect(self._on_user_profile_updated)

        # 系统组件联动
        self.state.editorDirtyChanged.connect(self._refresh_sidebar_badges)
        self.state.senderActiveChanged.connect(self._refresh_sidebar_badges)

        # 自动更新检查流
        self.system_controller.updateFound.connect(self._on_update_found)
        self.system_controller.updateNotFound.connect(lambda is_m:
            QMessageBox.information(self, "检查更新", "当前已是最新版本。") if is_m else None
        )
        self.system_controller.checkFailed.connect(lambda err, is_m:
            QMessageBox.warning(self, "检查更新失败", f"无法连接到更新服务器:\n{err}") if is_m else None
        )

        self.state.senderActiveChanged.connect(self._refresh_global_status)
        self.state.monitorActiveChanged.connect(self._refresh_global_status)

        self.page_sender.sender_controller.progressUpdated.connect(self._on_sender_progress_sync)
        self.page_monitor.monitor_controller.statsUpdated.connect(self._on_monitor_stats_sync)

        # 触发首次用户信息请求
        QTimer.singleShot(500, self._request_user_info_refresh)

    # endregion
    # region UI Updates & Slots

    @Slot(str, str)
    def _request_user_info_refresh(self):
        """收到凭证变更信号后，重置/开启防抖计时器"""
        self._auth_debounce_timer.start(800)

    @Slot()
    def _do_user_info_refresh(self):
        """真正的防抖执行函数"""
        sessdata = self.state.sessdata.strip()
        bili_jct = self.state.bili_jct.strip()

        if not sessdata:
            self._on_user_profile_updated(UserProfile(is_login=False, username="未登录"))
            return

        if len(sessdata) > 10 and not bili_jct:
            return

        self.auth_controller.refresh_user_info(self.state.get_api_auth())

    def _refresh_default_avatar(self):
        """通用方法：渲染高清的默认头像"""
        icon = get_svg_icon("default_avatar.svg")
        pixmap = icon.pixmap(36, 36)
        self.avatar_label.setPixmap(pixmap)

    @Slot(UserProfile)
    def _on_user_profile_updated(self, profile: UserProfile):
        """同步更新 UI"""
        # 更新文字
        self.username_label.setText(profile.username)

        # 更新头像
        if profile.is_login and profile.avatar_bytes:
            dpr = self.devicePixelRatioF()
            pixmap = QtImageProcessor.make_circular_pixmap(profile.avatar_bytes, 36, dpr)
            if not pixmap.isNull():
                self.avatar_label.setPixmap(pixmap)
                return

        # 未登录或无头像
        self._refresh_default_avatar()

    @Slot(bool)
    def _refresh_sidebar_badges(self, state_val: bool = False):
        """动态刷新侧边栏项目的文字后缀"""
        if sender_item := self.sidebar.item(1):
            sender_item.setText("弹幕发射器 ▶" if self.state.sender_is_active else "弹幕发射器")

        if editor_item := self.sidebar.item(2):
            editor_item.setText("弹幕编辑器 •" if self.state.editor_is_dirty else "弹幕编辑器")

    @Slot()
    def _open_log_folder(self):
        log_dir = Path(user_data_dir(AppInfo.NAME_EN, AppInfo.AUTHOR)) / AppInfo.LOG_DIR_NAME
        if not log_dir.exists():
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "错误", f"无法创建日志目录：\n{e}")
                return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    @Slot()
    def _show_help(self):
        """显示非模态的帮助窗口"""
        if not self._help_dialog:
            self._help_dialog = HelpDialog()
            self._help_dialog.finished.connect(lambda *args: setattr(self, '_help_dialog', None))

        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    @Slot()
    def _show_about(self):
        AboutDialog(self).exec()

    def _run_update_check(self, is_manual: bool = False):
        """启动更新检查"""
        self.system_controller.check_for_updates(self.state.sender_config.use_system_proxy, is_manual)

    @Slot(str, str, str)
    def _on_update_found(self, ver: str, notes: str, url: str):
        """发现新版本时的弹窗"""
        dialog = UpdateDialog(ver, notes, self)

        if dialog.exec():
            QDesktopServices.openUrl(QUrl(url))

    @Slot()
    def _show_from_tray(self):
        """从托盘恢复窗口"""
        self.showNormal()
        self.activateWindow()

    @Slot()
    def _force_quit(self):
        """强制退出程序"""
        self.tray_icon.hide()
        QApplication.quit()

    @Slot(QSystemTrayIcon.ActivationReason)
    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """单击托盘图标恢复窗口"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_from_tray()

    @Slot(int, int)
    def _on_sender_progress_sync(self, att: int, total: int):
        self._current_sender_progress = (att, total)
        self._refresh_global_status()

    @Slot(dict)
    def _on_monitor_stats_sync(self, stats: dict):
        self._current_monitor_stats = stats
        self._refresh_global_status()

    @Slot()
    def _refresh_global_status(self, _=None):
        # 组装发送器信息
        if self.state.sender_is_active:
            att, total = self._current_sender_progress
            perc = int((att/total)*100) if total > 0 else 0
            sender_info = f"发射器: {perc}% ({att}/{total})"
        else:
            sender_info = "发射器: 待命"

        # 组装监视器信息
        if self.state.monitor_is_active:
            s = self._current_monitor_stats
            monitor_info = f"监视器: 存活{s.get('verified',0)}/丢失{s.get('lost',0)}/待验{s.get('pending',0)}"
        else:
            monitor_info = "监视器: 待命"

        # 刷新托盘悬浮窗
        full_status = f"{AppInfo.NAME}\n{sender_info}\n{monitor_info}"
        self.tray_icon.setToolTip(full_status)

    @Slot()
    def _on_theme_changed(self, _):
        """当系统深浅色发生改变时，热重载全局 QSS 样式表"""
        load_stylesheet()

    # endregion