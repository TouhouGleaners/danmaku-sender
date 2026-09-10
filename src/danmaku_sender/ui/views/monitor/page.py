import logging
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QPushButton,
    QSpinBox, QTextEdit, QVBoxLayout, QWidget,
    QTableView, QHeaderView, QAbstractItemView,
)

from .table import QueueMonitorModel
from danmaku_sender.ui.framework.binder import UIBinder
from danmaku_sender.ui.framework.style_loader import SvgIcon

from danmaku_sender.types.models.common import MonitorStats
from danmaku_sender.types.models.queue import QueueTask, TaskStatus
from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.controller.monitor_controller import MonitorController


class MonitorPage(QWidget):
    """监视器页面 - 支持单任务监视和队列总体监视"""

    statsUpdated = Signal(dict)

    def __init__(self, state: AppState, history_manager: HistoryManager):
        super().__init__()
        self.state = state
        self.logger = logging.getLogger(__name__)
        self.history_manager = history_manager

        self.monitor_controller = MonitorController(history_manager, self)

        # 队列监视状态
        self._queue_monitoring = False
        self._queue_stats: dict[str, MonitorStats] = {}  # task_id -> stats

        # 队列监视轮询定时器（仅在监视运行期间激活）
        self._stats_timer = QTimer(self)

        self._create_ui()
        self._connect_signals()

        self._icon_start = SvgIcon("start.svg")
        self._icon_stop = SvgIcon("stop.svg")

    def _create_ui(self):
        # 主布局 - 垂直布局
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- 队列任务表格 ---
        queue_group = QGroupBox("队列任务状态")
        queue_layout = QVBoxLayout(queue_group)

        self.queue_table = QTableView()
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.queue_table.setAlternatingRowColors(True)
        self.queue_table.verticalHeader().setVisible(False)

        self._queue_model = QueueMonitorModel()
        self.queue_table.setModel(self._queue_model)

        header = self.queue_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)

        # 空状态引导
        self._empty_hint = QLabel("当前队列暂无任务  请先在「发射器」页面添加任务", self.queue_table.viewport())
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setStyleSheet("color: #888; font-size: 14px;")
        self._empty_hint.setVisible(False)
        self._queue_model.modelReset.connect(self._update_empty_hint)

        # 布局完成后再定位，避免 viewport geometry 为零
        QTimer.singleShot(0, self._update_empty_hint)

        queue_layout.addWidget(self.queue_table)
        main_layout.addWidget(queue_group)

        # --- 核心：数据仪表盘 ---
        stats_group = QGroupBox("整体统计")
        stats_layout = QGridLayout()
        stats_layout.setContentsMargins(20, 20, 20, 20)
        stats_layout.setHorizontalSpacing(30)

        def create_stat_block(title, color):
            lbl_num = QLabel("0")
            lbl_num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_num.setStyleSheet(f"font-size: 32px; font-weight: bold; color: {color}; font-family: 'Segoe UI', sans-serif;")

            lbl_title = QLabel(title)
            lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
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

        # 时间锚点选择区
        param_layout.addSpacing(20)
        param_layout.addWidget(QLabel("统计基线:"))

        # 下拉框
        self.anchor_combo = QComboBox()
        self.anchor_combo.setFixedWidth(115)
        self.anchor_combo.setPlaceholderText("手动指定")
        self.anchor_combo.addItem("本次启动后", "launch")
        self.anchor_combo.addItem("最近 24 小时", "24h")
        self.anchor_combo.addItem("全量历史", "all")
        param_layout.addWidget(self.anchor_combo)

        # 设为当前按钮
        self.btn_reset_anchor = QPushButton("设为当前")
        self.btn_reset_anchor.setToolTip("重置为当前时间，仅统计现在之后的发送记录，用于多批次任务对账。")
        self.btn_reset_anchor.setCursor(Qt.CursorShape.PointingHandCursor)
        param_layout.addWidget(self.btn_reset_anchor)

        # 状态展示
        self.anchor_display = QLabel("(尚未设置)")
        self.anchor_display.setMinimumWidth(130)
        self.anchor_display.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        param_layout.addWidget(self.anchor_display)
        param_layout.addStretch(1)

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

        self.btn_monitor_queue = QPushButton("监视队列")
        self.btn_monitor_queue.setIcon(SvgIcon("start.svg"))
        self.btn_monitor_queue.setFixedWidth(120)
        self.btn_monitor_queue.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_monitor_queue.setProperty("action", "true")
        self.btn_monitor_queue.setProperty("state", "ready")

        action_layout.addWidget(self.status_label, stretch=1)
        action_layout.addWidget(self.btn_monitor_queue)

        main_layout.addLayout(action_layout)

        self.setLayout(main_layout)

    def _connect_signals(self):
        # Internal
        self.btn_monitor_queue.clicked.connect(self._toggle_queue_monitor)
        self._stats_timer.timeout.connect(self._on_stats_tick)
        self.anchor_combo.currentIndexChanged.connect(self._on_anchor_changed)
        self.btn_reset_anchor.clicked.connect(self._on_reset_anchor_clicked)

        # MonitorController
        self.monitor_controller.statsUpdated.connect(self.statsUpdated.emit)
        self.monitor_controller.statusUpdated.connect(self.status_label.setText)
        self.monitor_controller.taskFinished.connect(self._on_finished)
        self.monitor_controller.queueVerifyFinished.connect(self._refresh_queue_stats)

        # QueueState
        self.state.queue_state.tasksChanged.connect(self._on_queue_changed)
        self.state.queue_state.taskStatusChanged.connect(self._on_queue_task_status_changed)

    def init_bindings(self):
        # 初始化与绑定
        UIBinder.bind(self.interval_spin, self.state.monitor_config, "refresh_interval")

        if self.state.monitor_config.stats_baseline == 0.0:
            self.state.monitor_config.stats_baseline = self.state.app_launch_time

            idx = self.anchor_combo.findData("launch")
            if idx >= 0:
                self.anchor_combo.blockSignals(True)
                self.anchor_combo.setCurrentIndex(idx)
                self.anchor_combo.blockSignals(False)

        self._update_anchor_display(self.state.monitor_config.stats_baseline)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_queue_table()

    def _update_btn_style(self, running: bool):
        """统一刷新按钮状态与图标"""
        state = "running" if running else "ready"
        self.btn_monitor_queue.setProperty("state", state)
        self.btn_monitor_queue.style().unpolish(self.btn_monitor_queue)
        self.btn_monitor_queue.style().polish(self.btn_monitor_queue)
        self.btn_monitor_queue.setIcon(self._icon_stop if running else self._icon_start)

    def _update_anchor_display(self, baseline: float):
        if baseline <= 0:
            self.anchor_display.setText("全量历史记录")
        else:
            dt_str = datetime.fromtimestamp(baseline).strftime('%m-%d %H:%M:%S')
            self.anchor_display.setText(dt_str)

    def _refresh_queue_table(self):
        """刷新队列任务表格"""
        tasks = self.state.queue_state.tasks
        self._queue_model.update_data(tasks, self._queue_stats)

    def _update_empty_hint(self):
        self._empty_hint.setVisible(self._queue_model.rowCount() == 0)
        self._reposition_empty_hint()

    def _reposition_empty_hint(self):
        self._empty_hint.setGeometry(self.queue_table.viewport().rect())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_empty_hint()

    def _update_overall_stats(self) -> dict:
        """更新整体统计卡片；只汇总当前队列中的任务（已移除的任务不计入）。返回合计值"""
        current_ids = {t.task_id for t in self.state.queue_state.tasks}
        totals = [s for tid, s in self._queue_stats.items() if tid in current_ids]

        total = sum(s.get('total', 0) for s in totals)
        verified = sum(s.get('verified', 0) for s in totals)
        pending = sum(s.get('pending', 0) for s in totals)
        lost = sum(s.get('lost', 0) for s in totals)

        self.lbl_total.setText(str(total))
        self.lbl_verified.setText(str(verified))
        self.lbl_pending.setText(str(pending))
        self.lbl_lost.setText(str(lost))
        return {'total': total, 'verified': verified, 'pending': pending, 'lost': lost}

    def _set_ui_running(self, running: bool):
        self.interval_spin.setEnabled(not running)
        self.btn_monitor_queue.setEnabled(True)

        self.state.monitor_is_active = running

        if running:
            self.btn_monitor_queue.setText("停止监视")
            self._update_btn_style(True)
            self.status_label.setText("监视器：运行中...")
        else:
            self.btn_monitor_queue.setText("监视队列")
            self._update_btn_style(False)
            self.status_label.setText("监视器：已停止")

    # region Slots
    # region Slots Internal
    @Slot()
    def _toggle_queue_monitor(self):
        """切换队列监视"""
        if self._queue_monitoring:
            # 停止队列监视
            self._queue_monitoring = False
            self._stats_timer.stop()
            self._queue_stats.clear()
            self._refresh_queue_table()
            self._update_overall_stats()
            self._set_ui_running(False)
            self.logger.info("⏹ 队列监视已停止")
            return

        # 启动队列监视
        tasks = self.state.queue_state.tasks
        if not tasks:
            QMessageBox.information(self, "队列为空", "没有任务可以监视。")
            return

        if not self.state.sessdata:
            QMessageBox.warning(self, "凭证缺失", "请先配置 Cookie。")
            return

        self._queue_monitoring = True
        self._queue_stats.clear()
        self._set_ui_running(True)
        self.logger.info(
            f"▶ 队列监视已启动：{len(tasks)} 个任务，轮询间隔 {self.interval_spin.value()} 秒"
        )

        # 立即执行第一轮，之后按轮询间隔循环
        self._on_stats_tick()
        self._stats_timer.start(self.interval_spin.value() * 1000)

    @Slot()
    def _on_stats_tick(self):
        """定时触发：发起一轮后台在线核销（不阻塞 UI），并刷新本地统计"""
        if not self._queue_monitoring:
            return

        tasks = self.state.queue_state.tasks
        cid_labels = [
            (task.target.cid, self._display_of(task))
            for task in tasks
            if task.status in (TaskStatus.COMPLETED, TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.PAUSED)
        ]
        if cid_labels:
            self.monitor_controller.verify_queue_online(cid_labels, self.state.get_api_auth())

        totals = self._refresh_queue_stats()
        if totals:
            baseline = self.state.monitor_config.stats_baseline
            anchor = "全量历史" if baseline <= 0 else datetime.fromtimestamp(baseline).strftime('%m-%d %H:%M')
            self.logger.info(
                f"统计(基线 {anchor}): 已发 {totals['total']} / 存活 {totals['verified']}"
                f" / 待验 {totals['pending']} / 疑似 {totals['lost']}"
            )

    @staticmethod
    def _display_of(task: QueueTask) -> str:
        """日志前缀，如 "P1 - 序章"；无分P信息时退回视频标题/BVID"""
        if task.p_index > 0 and task.p_title:
            return f"P{task.p_index} - {task.p_title}"
        return task.p_title or task.target.display_string

    def _refresh_queue_stats(self) -> dict | None:
        """从本地数据库刷新队列中所有任务的统计数据并渲染；返回合计值"""
        if not self._queue_monitoring:
            return

        tasks = self.state.queue_state.tasks
        baseline = self.state.monitor_config.stats_baseline

        for task in tasks:
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.RUNNING):
                # 查询该任务的统计数据
                stats = self.history_manager.get_stats_for_target(
                    target=task.target,
                    baseline=baseline
                )
                self._queue_stats[task.task_id] = stats

        self._refresh_queue_table()
        return self._update_overall_stats()

    @Slot(int)
    def _on_anchor_changed(self, index: int):
        if index < 0:
            return

        data = self.anchor_combo.currentData()
        new_baseline = 0.0
        if data == "launch":
            new_baseline = self.state.app_launch_time
        elif data == "24h":
            new_baseline = time.time() - 86400
        elif data == "all":
            new_baseline = 0.0

        self.state.monitor_config.stats_baseline = new_baseline
        self._update_anchor_display(new_baseline)

    @Slot()
    def _on_reset_anchor_clicked(self):
        current_ts = time.time()
        self.state.monitor_config.stats_baseline = current_ts
        self._update_anchor_display(current_ts)

        self.anchor_combo.blockSignals(True)
        self.anchor_combo.setCurrentIndex(-1)
        self.anchor_combo.blockSignals(False)

    # endregion
    # region Slots MonitorController
    @Slot()
    def _on_finished(self):
        self._set_ui_running(False)

    # endregion
    # region Slots QueueState
    @Slot()
    def _on_queue_changed(self):
        """队列变化时刷新表格"""
        self._refresh_queue_table()
        if self._queue_monitoring:
            self._refresh_queue_stats()

    @Slot(str, str)
    def _on_queue_task_status_changed(self, task_id: str, status: str):
        """任务状态变化时刷新统计数据"""
        if self._queue_monitoring:
            self._refresh_queue_stats()

    # endregion
    # endregion

    def append_log(self, message: str):
        self.log_output.append(message)
        self.log_output.moveCursor(QTextCursor.MoveOperation.End)
