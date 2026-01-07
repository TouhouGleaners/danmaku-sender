import logging
import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, 
    QLabel, QGroupBox, QTextEdit, QProgressBar, 
    QPushButton, QSpinBox, QFrame, QMessageBox
)
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import Qt, QThread, Signal

from ..api.bili_api_client import BiliApiClient
from ..core.bili_monitor import BiliDanmakuMonitor
from ..core.state import ApiAuthConfig, MonitorConfig
from ..utils.system_utils import KeepSystemAwake


class MonitorTaskWorker(QThread):
    """监视任务后台线程"""
    progress_updated = Signal(int, int)  # 匹配，总数
    status_updated = Signal(str)         # 状态更新
    log_message = Signal(str)            # 日志
    task_finished = Signal()

    def __init__(self, cid, danmakus,
                 auth_config: ApiAuthConfig,
                 monitor_config: MonitorConfig,
                 stop_event, parent=None):
        super().__init__(parent)
        self.cid = cid
        self.danmakus = danmakus
        self.auth_config = auth_config
        self.monitor_config = monitor_config
        self.stop_event = stop_event

    def run(self):
        try:
            with KeepSystemAwake(self.monitor_config.prevent_sleep):
                with BiliApiClient.from_config(self.auth_config) as client:
                    monitor = BiliDanmakuMonitor(
                        api_client=client,
                        cid=self.cid,
                        loaded_danmakus=self.danmakus,
                        interval=self.monitor_config.refresh_interval,
                        time_tolerance=self.monitor_config.tolerance
                    )

                    def _callback(matched, total):
                        self.progress_updated.emit(matched, total)
                        if total > 0:
                            self.status_updated.emit(f"监视中... ({matched}/{total})")

                    monitor.run(self.stop_event, _callback)
        
        except Exception as e:
            logging.getLogger("MonitorTaskWorker").error("监视任务异常", exc_info=True)
            self.log_message.emit(f"监视任务异常: {e}")
        finally:
            self.task_finished.emit()


class MonitorTab(QWidget):
    def __init__(self):
        super().__init__()
        self._state = None
        self._monitor_worker = None
        self.logger = logging.getLogger("MonitorTab")
        self.stop_event = threading.Event()
        self._is_running = False

        self._create_ui()
        self._connect_signals()

    def _create_ui(self):
        # 主布局 - 垂直布局
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- 监视状态与设置 ---
        settings_group = QGroupBox("监视状态与设置")
        settings_layout = QVBoxLayout()
        settings_layout.setContentsMargins(15, 15, 15, 15)

        # 当前视频详细信息
        info_layout = QFormLayout()
        info_layout.setLabelAlignment(Qt.AlignRight)
        info_layout.setVerticalSpacing(8)
        
        self.bvid_label = QLabel("尚未加载视频")
        self.bvid_label.setStyleSheet("font-weight: bold; color: #3498db;")
        
        self.part_label = QLabel("尚未选择分P")
        self.part_label.setStyleSheet("font-weight: bold; color: #3498db;")
        
        self.file_label = QLabel("尚未选择弹幕文件")
        self.file_label.setWordWrap(True)
        
        info_layout.addRow("当前视频:", self.bvid_label)
        info_layout.addRow("当前分P:", self.part_label)
        info_layout.addRow("本地文件:", self.file_label)
        
        settings_layout.addLayout(info_layout)
        
        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("margin: 5px 0;")
        settings_layout.addWidget(line)
        
        # 监视参数设置
        adv_layout = QHBoxLayout()
        
        adv_layout.addWidget(QLabel("检查间隔(秒):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 3600)
        self.interval_spin.setValue(60)
        self.interval_spin.setFixedWidth(80)
        adv_layout.addWidget(self.interval_spin)
        
        adv_layout.addSpacing(30)
        
        adv_layout.addWidget(QLabel("时间容差(ms):"))
        self.tolerance_spin = QSpinBox()
        self.tolerance_spin.setRange(0, 5000)
        self.tolerance_spin.setValue(500)
        self.tolerance_spin.setSingleStep(100)
        self.tolerance_spin.setFixedWidth(80)
        adv_layout.addWidget(self.tolerance_spin)
        
        adv_layout.addStretch()
        
        settings_layout.addLayout(adv_layout)
        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)

        # --- 运行日志区 ---
        log_group = QGroupBox("监视运行日志")
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(5, 10, 5, 5)
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("font-family: 'Consolas', 'Monaco', monospace; font-size: 12px;")
        
        log_layout.addWidget(self.log_output)
        log_group.setLayout(log_layout)
        
        main_layout.addWidget(log_group, stretch=1)

        # --- 底部控制栏 ---
        action_layout = QHBoxLayout()
        action_layout.setSpacing(15)
        
        self.status_label = QLabel("监视器：待命")
        self.status_label.setStyleSheet("color: #7f8c8d;")
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        
        self.start_btn = QPushButton("开始监视")
        self.start_btn.setFixedWidth(120)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #2ecc71; 
                color: white; 
                font-weight: bold; 
                padding: 6px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #27ae60;
            }
        """)
        
        action_layout.addWidget(self.status_label)
        action_layout.addWidget(self.progress_bar, stretch=1)
        action_layout.addWidget(self.start_btn)
        
        main_layout.addLayout(action_layout)

        self.setLayout(main_layout)

    def _connect_signals(self):
        self.start_btn.clicked.connect(self.toggle_task)

    def bind_state(self, state):
        if self._state is state:
            return

        if self._state is not None:
            self._disconnect_signals()

        self._state = state
        config = state.monitor_config

        # 初始化与绑定
        self.interval_spin.blockSignals(True)
        self.tolerance_spin.blockSignals(True)

        self.interval_spin.setValue(config.refresh_interval)
        self.tolerance_spin.setValue(config.tolerance)

        self.interval_spin.blockSignals(False)
        self.tolerance_spin.blockSignals(False)

        self.interval_spin.valueChanged.connect(self._on_interval_changed)
        self.tolerance_spin.valueChanged.connect(self._on_tolerance_changed)

    def _disconnect_signals(self):
        try:
            self.interval_spin.valueChanged.disconnect(self._on_interval_changed)
            self.tolerance_spin.valueChanged.disconnect(self._on_tolerance_changed)
        except (RuntimeError, TypeError):
            pass

    def _on_interval_changed(self, value):
        if self._state:
            self._state.monitor_config.refresh_interval = value

    def _on_tolerance_changed(self, value):
        if self._state:
            self._state.monitor_config.tolerance = value

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_info_labels()

    def _refresh_info_labels(self):
        if not self._state:
            return
        
        video_state = self._state.video_state
        
        self.bvid_label.setText(video_state.bvid if video_state.bvid else "尚未加载")
        self.part_label.setText(video_state.selected_part_name if video_state.selected_part_name else "尚未选择")
        self.file_label.setText(f"已加载 {len(video_state.loaded_danmakus)} 条弹幕" if video_state.loaded_danmakus else "尚未选择文件")

    def toggle_task(self):
        if not self._state:
            return
        
        if self._is_running:
            self.stop_event.set()
            self.start_btn.setText("正在停止...")
            self.start_btn.setEnabled(False)
            return
        
        if self._monitor_worker is not None and self._monitor_worker.isRunning():
            self.logger.warning("上一轮任务尚未彻底结束，请稍候...")
            return
        
        video_state = self._state.video_state
        if not video_state.is_ready_to_send:
            QMessageBox.warning(self, "无法启动", "请先在“发射器”页面加载视频和弹幕文件。")
            return
        
        if not self._state.sessdata:
            QMessageBox.warning(self, "凭证缺失", "请先配置 Cookie。")
            return
        
        self._set_ui_running(True)

        auth = self._state.get_api_auth()
        monitor_config = self._state.monitor_config

        self._monitor_worker = MonitorTaskWorker(
            cid=video_state.selected_cid,
            danmakus=video_state.loaded_danmakus,
            auth_config=auth,
            monitor_config=monitor_config,
            stop_event=self.stop_event,
            parent=self
        )
        self._monitor_worker.progress_updated.connect(self._on_progress)
        self._monitor_worker.status_updated.connect(self.status_label.setText)
        self._monitor_worker.log_message.connect(self.append_log)
        self._monitor_worker.task_finished.connect(self._on_finished)
        self._monitor_worker.finished.connect(self._monitor_worker.deleteLater)
        self._monitor_worker.start()

    def _set_ui_running(self, running):
        self._is_running = running
        self.stop_event.clear()
        
        self.interval_spin.setEnabled(not running)
        self.tolerance_spin.setEnabled(not running)
        self.start_btn.setEnabled(True)
        
        if running:
            self.start_btn.setText("停止监视")
            self.start_btn.setStyleSheet("""
                QPushButton {
                    background-color: #e74c3c;
                    color: white;
                    font-weight: bold;
                    padding: 6px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #c0392b;
                    }
            """)
            self.log_output.clear()
            self.progress_bar.setValue(0)
            self.status_label.setText("监视器：启动中...")
        else:
            self.start_btn.setText("开始监视")
            self.start_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2ecc71; 
                    color: white; 
                    font-weight: bold; 
                    padding: 6px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #27ae60;
                }
            """)
            self.status_label.setText("监视器：已停止")

    def _on_progress(self, matched, total):
        if total > 0:
            val = int((matched / total) * 100)
            self.progress_bar.setValue(val)

    def _on_finished(self):
        self._set_ui_running(False)
        self._monitor_worker = None

    def append_log(self, message: str):
        self.log_output.append(message)
        self.log_output.moveCursor(QTextCursor.End)