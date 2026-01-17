import logging
import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QTextEdit, 
    QPushButton, QSpinBox, QMessageBox, QGridLayout
)
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import Qt

from ..core.models.structs import VideoTarget
from ..core.workers import MonitorTaskWorker


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

        # --- 顶部：目标信息 ---
        info_group = QGroupBox("监视目标")
        info_layout = QHBoxLayout()

        self.target_label = QLabel("尚未选择视频")
        self.target_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #34495e;")

        info_layout.addWidget(QLabel("当前目标:"))
        info_layout.addWidget(self.target_label, stretch=1)
        
        info_group.setLayout(info_layout)
        main_layout.addWidget(info_group)

        # --- 核心：数据仪表盘 ---
        stats_group = QGroupBox("数据审计")
        stats_layout = QGridLayout()
        stats_layout.setContentsMargins(20, 20, 20, 20)
        stats_layout.setHorizontalSpacing(30)

        def create_stat_block(title, color):
            lbl_num = QLabel("0")
            lbl_num.setAlignment(Qt.AlignCenter)
            lbl_num.setStyleSheet(f"font-size: 32px; font-weight: bold; color: {color}; font-family: 'Segoe UI', sans-serif;")
            
            lbl_title = QLabel(title)
            lbl_title.setAlignment(Qt.AlignCenter)
            lbl_title.setStyleSheet("color: #7f8c8d; font-size: 12px;")

            container = QVBoxLayout()
            container.addWidget(lbl_num)
            container.addWidget(lbl_title)
            return lbl_num, container

        # 总发送
        self.lbl_total, layout_total = create_stat_block("已发送 (Total)", "#2c3e50")
        # 存活
        self.lbl_verified, layout_verified = create_stat_block("已存活 (Verified)", "#27ae60")
        # 待验
        self.lbl_pending, layout_pending = create_stat_block("待验证 (Pending)", "#f39c12")
        # 丢失
        self.lbl_lost, layout_lost = create_stat_block("疑似丢失 (Lost)", "#c0392b")

        stats_layout.addLayout(layout_total, 0, 0)
        stats_layout.addLayout(layout_verified, 0, 1)
        stats_layout.addLayout(layout_pending, 0, 2)
        stats_layout.addLayout(layout_lost, 0, 3)

        stats_group.setLayout(stats_layout)
        main_layout.addWidget(stats_group)

        # --- 设置与日志 ---
        param_layout = QHBoxLayout()
        param_layout.addWidget(QLabel("轮询间隔(秒):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(10, 3600)
        self.interval_spin.setValue(60)
        param_layout.addWidget(self.interval_spin)
        
        param_layout.addStretch()
        
        main_layout.addLayout(param_layout)

        # 日志区
        log_group = QGroupBox("监视日志")
        log_layout = QVBoxLayout()
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("font-family: 'Consolas', monospace; font-size: 11px;")
        log_layout.addWidget(self.log_output)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group, stretch=1)

        # --- 底部控制 ---
        action_layout = QHBoxLayout()
        self.status_label = QLabel("监视器：待命")
        
        self.start_btn = QPushButton("开始监视")
        self.start_btn.setFixedWidth(100)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setProperty("action", "true")
        self.start_btn.setProperty("state", "ready")
        
        action_layout.addWidget(self.status_label, stretch=1)
        action_layout.addWidget(self.start_btn)
        
        main_layout.addLayout(action_layout)

        self.setLayout(main_layout)

    def _update_btn_style(self, running: bool):
        state = "running" if running else "ready"
        self.start_btn.setProperty("state", state)
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)

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
        self.interval_spin.setValue(config.refresh_interval)
        self.interval_spin.blockSignals(False)
        self.interval_spin.valueChanged.connect(self._on_interval_changed)

    def _disconnect_signals(self):
        try:
            self.interval_spin.valueChanged.disconnect(self._on_interval_changed)
        except (RuntimeError, TypeError):
            pass

    def _on_interval_changed(self, value):
        if self._state:
            self._state.monitor_config.refresh_interval = value

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_info_labels()

    def _refresh_info_labels(self):
        if not self._state:
            return
        
        video_state = self._state.video_state
        
        if video_state.selected_cid:
            title = video_state.video_title[:20] + "..." if len(video_state.video_title) > 20 else video_state.video_title
            part = video_state.selected_part_name
            self.target_label.setText(f"{title} - {part} (CID: {video_state.selected_cid})")
        else:
            self.target_label.setText("尚未选择视频 (请在发射器页面加载)")

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
        
        cid = self._state.video_state.selected_cid
        bvid = self._state.video_state.bvid
        title = self._state.video_state.video_title

        if not cid:
            QMessageBox.warning(self, "无法启动", "请先在“发射器”页面获取视频信息并选择分P。\n(监视器需要 CID 来查询数据库)")
            return
        
        if not self._state.sessdata:
            QMessageBox.warning(self, "凭证缺失", "请先配置 Cookie。")
            return
        
        self._set_ui_running(True)

        auth = self._state.get_api_auth()
        monitor_config = self._state.monitor_config

        target = VideoTarget(bvid=bvid, cid=cid, title=title)

        self._monitor_worker = MonitorTaskWorker(
            target=target,
            auth_config=auth,
            monitor_config=monitor_config,
            stop_event=self.stop_event,
            parent=self
        )
        self._monitor_worker.stats_updated.connect(self._on_stats_updated)
        self._monitor_worker.status_updated.connect(self.status_label.setText)
        self._monitor_worker.log_message.connect(self.append_log)
        self._monitor_worker.task_finished.connect(self._on_finished)
        self._monitor_worker.finished.connect(self._monitor_worker.deleteLater)
        self._monitor_worker.start()

    def _set_ui_running(self, running):
        self._is_running = running
        self.stop_event.clear()
        
        self.interval_spin.setEnabled(not running)
        self.start_btn.setEnabled(True)
        
        if running:
            self.start_btn.setText("停止监视")
            self._update_btn_style(True)
            self.log_output.clear()
            self.status_label.setText("监视器：启动中...")
        else:
            self.start_btn.setText("开始监视")
            self._update_btn_style(False)
            self.status_label.setText("监视器：已停止")

    def _on_stats_updated(self, stats: dict):
        """
        处理后端传回的统计数据
        stats: {'total': int, 'verified': int, 'pending': int, 'lost': int}
        """
        self.lbl_total.setText(str(stats.get('total', 0)))
        self.lbl_verified.setText(str(stats.get('verified', 0)))
        self.lbl_pending.setText(str(stats.get('pending', 0)))
        self.lbl_lost.setText(str(stats.get('lost', 0)))

    def _on_finished(self):
        self._set_ui_running(False)
        self._monitor_worker = None

    def append_log(self, message: str):
        self.log_output.append(message)
        self.log_output.moveCursor(QTextCursor.End)