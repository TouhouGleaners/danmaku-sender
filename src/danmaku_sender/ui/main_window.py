import logging

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDesktopServices,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from danmaku_sender.config import Settings
from danmaku_sender.config.app_meta import UI, AppInfo, Links
from danmaku_sender.controller.auth_controller import AuthController
from danmaku_sender.controller.monitor import MonitorController
from danmaku_sender.controller.system_controller import SystemController
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.state import AppState
from danmaku_sender.types.models.common import MonitorStats
from danmaku_sender.types.models.user import UserProfile
from danmaku_sender.ui.support.log_utils import GuiLoggingHandler

from .dialogs import AboutDialog, UpdateDialog
from .framework.fonts import FontService
from .framework.icons import SvgIcon, get_app_icon
from .framework.image_processor import QtImageProcessor
from .framework.notification import Notification
from .framework.theme import Palette, ThemeService
from .views.account import AccountDialog
from .views.history import HistoryPage
from .views.monitor import MonitorPage
from .views.sender import SenderPage
from .views.settings import SettingsPage


class MainWindow(QMainWindow):
    # region Lifecycle & Initialization
    def __init__(
        self,
        state: AppState,
        settings: Settings,
        history_manager: HistoryManager,
    ):
        """初始化主窗口。

        Args:
            state: 状态树聚合根。
            settings: 配置容器。
            history_manager: 本地账本。
        """
        super().__init__()
        self.state = state
        self.settings = settings
        self.history_manager = history_manager

        self.setWindowTitle(UI.MAIN_WINDOW_TITLE)
        self.resize(900, 680)

        # 主题服务（UI 层持有，订阅 theme_config 变更驱动）
        self.theme_service = ThemeService(self)

        # 字体服务（与主题服务平级，同为外观基础设施）
        self.font_service = FontService(self)

        # 首屏外观必须在创建任何 UI 控件前生效，否则 SvgIcon 会拿到错误的调色板颜色，
        # 控件也会按旧字体测量
        self.theme_service.apply_theme(self.settings.theme_config.theme_mode)
        self.font_service.apply(self.settings.theme_config.font_name)

        # 控制器
        self.auth_controller = AuthController(self.state, self.settings, self)
        self.system_controller = SystemController(self)
        # 队列监视控制器由本窗持有并注入各页，供发射器与监视器页共用
        self.monitor_controller = MonitorController(self.state, self.settings, self.history_manager, self)
        self.logger = logging.getLogger(__name__)
        self._log_signals_connected = False
        self._current_profile: UserProfile | None = None

        # 运行时状态
        self._current_sender_progress = (0, 0)
        self._current_monitor_stats: MonitorStats = {'total': 0, 'verified': 0, 'pending': 0, 'lost': 0}

        # UI 初始化
        self._create_ui()
        self._init_pages()
        self._init_shortcuts()
        self._create_menu_bar()
        self._init_system_tray()

        # 主题链路：设置页写配置 → themeApplied 显式信号 → 立即应用（无隐式订阅）
        self.page_settings.themeApplied.connect(self.theme_service.apply_theme)
        self.theme_service.themeChanged.connect(self._on_theme_applied)

        # 字体链路同形
        self.page_settings.fontApplied.connect(self.font_service.apply)

        # 信号与状态绑定
        self._init_auth_system()
        self._bind_state_to_pages()
        self._connect_global_signals()

        QTimer.singleShot(1000, lambda: self._run_update_check(is_manual=False))

    def changeEvent(self, event: QEvent):
        """窗口状态变化: 最小化到托盘"""
        super().changeEvent(event)

        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            self.hide()
            self.tray_icon.showMessage(
                AppInfo.NAME,
                "程序已最小化到托盘，后台监视/发送任务将继续运行。",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )

    def closeEvent(self, event: QCloseEvent):
        """窗口关闭事件。配置与凭据由装配总线在退出时落盘。"""
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
        self._render_avatar()

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
        self.content_stack.setObjectName("contentStack")

        self.main_layout.addWidget(self.sidebar_frame)
        self.main_layout.addWidget(self.content_stack)

        # 右下角通知卡片堆
        Notification.install(self.central_widget)

    def _init_pages(self):
        """初始化页面并绑定导航"""
        self.page_settings = SettingsPage(self.state, self.settings)
        self.page_sender = SenderPage(
            self.state, self.settings, self.history_manager, self.monitor_controller
        )
        self.page_monitor = MonitorPage(
            self.state, self.settings, self.history_manager, self.monitor_controller
        )
        self.page_history = HistoryPage(self.state, self.settings, self.history_manager)

        # 侧边栏导航页面（图标在 _refresh_icons 中按需重新获取）
        sidebar_entries = [
            ("全局设置", self.page_settings, SvgIcon.SETTINGS),
            ("弹幕发射器", self.page_sender, SvgIcon.SEND),
            ("弹幕监视器", self.page_monitor, SvgIcon.MONITOR),
            ("弹幕历史记录", self.page_history, SvgIcon.HISTORY),
        ]

        for title, widget, icon in sidebar_entries:
            item = QListWidgetItem(icon, title)
            self.sidebar.addItem(item)
            self.content_stack.addWidget(widget)

        self.sidebar.currentRowChanged.connect(self.content_stack.setCurrentIndex)
        self.sidebar.setCurrentRow(1)

        # 补设首屏强调色
        self.page_sender.apply_theme(self.theme_service.current_palette)

        # 用户页眉点击打开账号管理弹窗
        self.user_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        self.user_widget.mousePressEvent = lambda e: self._open_account_dialog()

    def _init_shortcuts(self):
        """初始化全局快捷键"""
        # Ctrl+N: 新建任务
        self._sc_new = QShortcut(QKeySequence.StandardKey.New, self)
        self._sc_new.activated.connect(self.page_sender._add_to_queue)

        # Ctrl+Enter: 启动队列
        self._sc_send = QShortcut(QKeySequence(Qt.Key.Key_Return | Qt.KeyboardModifier.ControlModifier), self)
        self._sc_send.activated.connect(self.page_sender._start_queue)

        # Ctrl+,: 打开全局设置
        self._sc_settings = QShortcut(QKeySequence(Qt.Key.Key_Comma | Qt.KeyboardModifier.ControlModifier), self)
        self._sc_settings.activated.connect(lambda: self.sidebar.setCurrentRow(0))

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
        usage_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(Links.GITHUB_PAGES)))
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
        self._auth_debounce_timer.timeout.connect(self._refresh_user_info)

    def _open_account_dialog(self):
        """打开账号管理弹窗"""
        dialog = AccountDialog(self.state, self.settings, self)
        dialog.exec()

    def _bind_state_to_pages(self):
        """绑定全局状态并配置日志路由"""
        # 页面数据绑定
        self.page_settings.init_bindings()
        self.page_monitor.init_bindings()
        self.page_history.init_bindings()

        # 日志分流：Handler 信号 -> Tab 接口
        self._setup_log_routing()

    def _setup_log_routing(self):
        """把 GuiLoggingHandler 的日志信号接到日志面板。"""
        root_logger = logging.getLogger()
        gui_handler = next(
            (h for h in root_logger.handlers if isinstance(h, GuiLoggingHandler)),
            None,
        )
        if gui_handler is None:
            self.logger.error("日志路由系统初始化失败：未找到 GuiLoggingHandler。")
            return

        if self._log_signals_connected:
            gui_handler.senderLogReceived.disconnect(self.page_sender.append_log)
            gui_handler.monitorLogReceived.disconnect(self.page_monitor.append_log)

        gui_handler.senderLogReceived.connect(self.page_sender.append_log)
        gui_handler.monitorLogReceived.connect(self.page_monitor.append_log)
        self._log_signals_connected = True
        self.logger.info("日志路由链路已接通。")

    def _connect_global_signals(self):
        """全局信号绑定"""
        # 用户认证与基础信息
        self.state.session.credentialsChanged.connect(lambda: self._auth_debounce_timer.start(800))
        self.auth_controller.userProfileReady.connect(self._on_user_profile_updated)

        # 自动更新检查流
        self.system_controller.updateFound.connect(self._on_update_found)
        self.system_controller.updateNotFound.connect(lambda is_m:
            QMessageBox.information(self, "检查更新", "当前已是最新版本。") if is_m else None
        )
        self.system_controller.checkFailed.connect(lambda err, is_m:
            QMessageBox.warning(self, "检查更新失败", f"无法连接到更新服务器:\n{err}") if is_m else None
        )

        self.state.workspace.senderActiveChanged.connect(self._refresh_global_status)
        self.state.workspace.monitorActiveChanged.connect(self._refresh_global_status)

        self.page_sender.progressUpdated.connect(self._on_sender_progress_sync)
        self.page_monitor.statsUpdated.connect(self._on_monitor_stats_sync)

        # 触发首次用户信息请求
        QTimer.singleShot(500, self._refresh_user_info)

    # endregion
    # region UI Updates & Slots

    @Slot()
    def _refresh_user_info(self):
        """刷新用户信息"""
        sessdata = self.state.session.sessdata.strip()
        bili_jct = self.state.session.bili_jct.strip()

        if not sessdata:
            self._on_user_profile_updated(UserProfile(is_login=False, username="未登录"))
            return

        if len(sessdata) > 20 and not bili_jct:
            return

        self.auth_controller.refresh_user_info()

    def _render_avatar(self):
        """统一头像渲染：已登录显示真实头像，未登录显示随主题变色的默认 SVG"""
        if self._current_profile and self._current_profile.is_login and self._current_profile.avatar_bytes:
            dpr = self.devicePixelRatioF()
            pixmap = QtImageProcessor.make_circular_pixmap(self._current_profile.avatar_bytes, 36, dpr)
            if not pixmap.isNull():
                self.avatar_label.setPixmap(pixmap)
                return

        # 未登录或无头像：用当前主题前景色渲染默认 SVG
        pixmap = SvgIcon.DEFAULT_AVATAR.pixmap(36, 36)
        self.avatar_label.setPixmap(pixmap)

    @Slot(UserProfile)
    def _on_user_profile_updated(self, profile: UserProfile):
        """同步更新 UI；昵称登记由授权控制器完成。"""
        self._current_profile = profile
        self.username_label.setText(profile.username)
        self._render_avatar()

    @Slot()
    def _open_log_folder(self):
        log_dir = AppInfo.Paths.LOGS
        if not log_dir.exists():
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                QMessageBox.warning(self, "错误", f"无法创建日志目录：\n{e}")
                return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    @Slot()
    def _show_about(self):
        AboutDialog(self).exec()

    def _run_update_check(self, is_manual: bool = False):
        """启动更新检查"""
        self.system_controller.check_for_updates(self.settings.global_config.use_system_proxy, is_manual)

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

    @Slot(int, int, float)
    def _on_sender_progress_sync(self, att: int, total: int, eta_sec: float):
        self._current_sender_progress = (att, total)
        self._refresh_global_status()

    @Slot(dict)
    def _on_monitor_stats_sync(self, stats: MonitorStats):
        self._current_monitor_stats = stats
        self._refresh_global_status()

    @Slot()
    def _refresh_global_status(self):
        # 组装发送器信息
        if self.state.workspace.sender_is_active:
            att, total = self._current_sender_progress
            perc = int((att/total)*100) if total > 0 else 0
            sender_info = f"发射器: {perc}% ({att}/{total})"
        else:
            sender_info = "发射器: 待命"

        # 组装监视器信息
        if self.state.workspace.monitor_is_active:
            s = self._current_monitor_stats
            monitor_info = f"监视器: 存活{s.get('verified',0)}/丢失{s.get('lost',0)}/待验{s.get('pending',0)}"
        else:
            monitor_info = "监视器: 待命"

        # 刷新托盘悬浮窗
        full_status = f"{AppInfo.NAME}\n{sender_info}\n{monitor_info}"
        self.tray_icon.setToolTip(full_status)

    @Slot(Palette)
    def _on_theme_applied(self, palette: Palette):
        """主题应用完成后，刷新需要重绘颜色的位图资源"""
        self.page_sender.apply_theme(palette)
        self._refresh_icons()

    def _refresh_icons(self):
        """主题切换后重刷所有使用主题前景色的图标"""
        # 侧边栏导航图标：重新访问描述符获取新主题颜色
        icons = [SvgIcon.SETTINGS, SvgIcon.SEND, SvgIcon.MONITOR, SvgIcon.HISTORY]
        for i, icon in enumerate(icons):
            self.sidebar.item(i).setIcon(icon)

        # 设置页行内图标
        self.page_settings.refresh_icons()

        # 头像
        self._render_avatar()

    # endregion