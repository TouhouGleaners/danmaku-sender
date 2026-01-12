import logging
from pathlib import Path
from platformdirs import user_data_dir

from PySide6.QtWidgets import QMainWindow, QTabWidget, QMessageBox
from PySide6.QtGui import QCloseEvent, QDesktopServices, QAction
from PySide6.QtCore import QUrl, QTimer

from .sender_tab import SenderTab
from .settings_tab import SettingsTab
from .monitor_tab import MonitorTab
from .validator_tab import ValidatorTab
from .dialogs import AboutDialog, HelpDialog 

from ..config.app_config import AppInfo, UI
from ..core.state import AppState
from ..core.workers import UpdateCheckWorker
from ..utils.log_utils import GuiLoggingHandler
from ..utils.credential_manager import load_credentials, save_credentials
from ..utils.config_manager import load_app_config, save_app_config
from ..utils.resource_utils import load_stylesheet


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(UI.MAIN_WINDOW_TITLE)
        self.resize(710, 650)

        # 核心状态
        self.state = AppState()
        self._log_signals_connected = False
        self.logger = logging.getLogger("MainWindow")

        # 中央部件
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # 初始化各页面
        self.init_tabs()
        self.create_menu_bar()

        # 从磁盘中加载凭证
        self._load_initial_credentials()
        load_app_config(self.state)

        # 绑定 State 到各个 Tab
        self.bind_state_to_tabs()
        load_stylesheet()

        # 存储帮助窗口的引用，防止被垃圾回收
        self._help_dialog = None 

        QTimer.singleShot(1000, lambda: self.run_update_check(is_manual=False))

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

    def bind_state_to_tabs(self):
        """绑定全局状态并配置日志路由"""
        # 页面数据绑定
        self.tab_settings.bind_state(self.state)
        self.tab_sender.bind_state(self.state)
        self.tab_validator.bind_state(self.state)
        self.tab_monitor.bind_state(self.state)

        # 日志分流：信号 -> Tab 接口
        if self._log_signals_connected:
            self.state.sender_log_received.disconnect(self.tab_sender.append_log)
            self.state.monitor_log_received.disconnect(self.tab_monitor.append_log)

        self.state.sender_log_received.connect(self.tab_sender.append_log)
        self.state.monitor_log_received.connect(self.tab_monitor.append_log)
        self._log_signals_connected = True

        # 信号接入：底层 Handler -> 信号发射
        self._setup_log_routing()

    def _setup_log_routing(self):
        """将 GuiLoggingHandler 的回调挂载到信号发射方法上"""
        # 筛选出所有 GUI 处理器并注入回调
        gui_handlers = [h for h in logging.getLogger().handlers if isinstance(h, GuiLoggingHandler)]
        
        for h in gui_handlers:
            h.sender_callback = self.state.sender_log_received.emit
            h.monitor_callback = self.state.monitor_log_received.emit
            
        if not gui_handlers:
            self.logger.warning("日志路由失败：未找到 GuiLoggingHandler。")

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
        if hasattr(self, '_update_worker') and self._update_worker and self._update_worker.isRunning():
            return
        
        use_proxy = self.state.sender_config.use_system_proxy
        self._update_worker = UpdateCheckWorker(use_proxy, is_manual, parent=self)
        self._update_worker.update_found.connect(self._on_update_found)

        if is_manual:
            self._update_worker.no_update.connect(lambda: QMessageBox.information(self, "检查更新", "当前已是最新版本。"))

        self._update_worker.start()

    def _on_update_found(self, ver, notes, url):
        """发现新版本时的弹窗"""
        # 简单的文本截断
        if len(notes) > 500:
            notes = notes[:500] + "\n... (更多内容请查看网页)"
            
        reply = QMessageBox.question(
            self, 
            f"发现新版本 v{ver}",
            f"发现新版本: v{ver}\n\n--- 更新内容 ---\n{notes}\n\n是否前往下载？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl(url))