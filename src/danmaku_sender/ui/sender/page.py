import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QDialog,
    QGroupBox, QTextEdit, QProgressBar, QFileDialog, QMessageBox,
    QTableView, QHeaderView, QAbstractItemView, QMenu
)
from PySide6.QtGui import QTextCursor, QDragEnterEvent, QDropEvent, QShortcut, QKeySequence
from PySide6.QtCore import Qt, QPoint, QDateTime, Signal, Slot

from .components import StrategySettingsTabs, BasicParamsGroup, PreSendDialog, QueueTableModel
from .components.queue_table import ProgressBarDelegate
from .data_binding import SenderDataBinding

from danmaku_sender.ui.framework.style_loader import SvgIcon
from danmaku_sender.controller.video_controller import VideoController
from danmaku_sender.controller.sender_controller import SenderController, SenderStatus, SenderState
from danmaku_sender.types.models.video import VideoInfo
from danmaku_sender.types.models.common import VideoTarget, UnsentDanmakusRecord
from danmaku_sender.types.models.queue import QueueTask, TaskStatus
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.service.sender import SendingContext
from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.ui.common.notification import send_windows_notification
from danmaku_sender.utils.time_utils import format_duration


class SenderPage(QWidget):
    progressUpdated = Signal(int, int, float)

    def __init__(self, state: AppState, history_manager: HistoryManager):
        super().__init__()
        self.state = state
        self.logger = logging.getLogger(__name__)
        self.video_controller = VideoController(self)
        self.sender_controller = SenderController(state, history_manager, self)
        self.binding = SenderDataBinding(state, self.sender_controller, self.video_controller, self)

        self._queue_total = 0
        self._queue_current = 0
        self._queue_total_dm: int = 0
        self._queue_eta: float = 0.0

        self._create_ui()
        self._connect_signals()

        self._icon_start = SvgIcon("start.svg")
        self._icon_stop = SvgIcon("stop.svg")

        self.setAcceptDrops(True)  # 全局拖拽接收

    def _create_ui(self):
        # 主布局 - 垂直布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- 基础参数策略区 ---
        self.basic_group = BasicParamsGroup(self.state)
        self.strategy_tabs = StrategySettingsTabs(self.state)

        main_layout.addWidget(self.basic_group)
        main_layout.addWidget(self.strategy_tabs)

        # --- 队列区 ---
        queue_group = QGroupBox("发送队列")
        queue_layout = QVBoxLayout(queue_group)

        self._queue_model = QueueTableModel()
        self._queue_table = QTableView()
        self._queue_table.setModel(self._queue_model)
        self._queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._queue_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._queue_table.setAlternatingRowColors(True)
        self._queue_table.verticalHeader().setVisible(False)

        header = self._queue_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(5, 120)

        self._progress_delegate = ProgressBarDelegate(self._queue_table)
        self._queue_table.setItemDelegateForColumn(5, self._progress_delegate)

        # 拖拽排序
        self._queue_table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._queue_table.setDragDropOverwriteMode(False)

        # 右键菜单
        self._queue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._queue_table.customContextMenuRequested.connect(self._on_queue_context_menu)

        # 键盘删除
        QShortcut(QKeySequence.StandardKey.Delete, self._queue_table, self._delete_selected_task)

        queue_layout.addWidget(self._queue_table)

        queue_btn_layout = QHBoxLayout()

        self._btn_add_to_queue = QPushButton("添加到队列")
        self._btn_add_to_queue.setIcon(SvgIcon("start.svg"))
        self._btn_add_to_queue.setFixedWidth(120)
        self._btn_add_to_queue.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_add_to_queue.setProperty("action", "true")
        self._btn_add_to_queue.setProperty("state", "ready")

        self._btn_start_queue = QPushButton("启动队列")
        self._btn_start_queue.setFixedWidth(100)
        self._btn_start_queue.setCursor(Qt.CursorShape.PointingHandCursor)

        self._btn_stop_queue = QPushButton("停止队列")
        self._btn_stop_queue.setFixedWidth(100)
        self._btn_stop_queue.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_stop_queue.setEnabled(False)

        self._btn_clear_completed = QPushButton("清除已完成")
        self._btn_clear_completed.setFixedWidth(100)
        self._btn_clear_completed.setCursor(Qt.CursorShape.PointingHandCursor)

        queue_btn_layout.addWidget(self._btn_add_to_queue)
        queue_btn_layout.addWidget(self._btn_start_queue)
        queue_btn_layout.addWidget(self._btn_stop_queue)
        queue_btn_layout.addWidget(self._btn_clear_completed)
        queue_btn_layout.addStretch()

        queue_layout.addLayout(queue_btn_layout)
        main_layout.addWidget(queue_group)

        # --- 日志区 ---
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout(log_group)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)

        main_layout.addWidget(log_group, stretch=1)

        # --- 操作区 ---
        action_layout = QHBoxLayout()

        # 状态
        self.status_label = QLabel("发送器：待命")

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        # 按钮
        self.start_btn = QPushButton("开始发送")
        self.start_btn.setIcon(SvgIcon("start.svg"))
        self.start_btn.setFixedWidth(100)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setProperty("action", "true")
        self.start_btn.setProperty("state", "ready")

        action_layout.addWidget(self.status_label)
        action_layout.addWidget(self.progress_bar, stretch=1)
        action_layout.addWidget(self.start_btn)

        main_layout.addLayout(action_layout)

        # 拖放覆盖层
        self._drop_overlay = QWidget(self)
        self._drop_overlay.setStyleSheet("background-color: rgba(0, 0, 0, 0.4);")
        overlay_layout = QVBoxLayout(self._drop_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        overlay_icon = QLabel()
        overlay_icon.setPixmap(SvgIcon("file_open.svg").pixmap(48, 48))
        overlay_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_icon.setStyleSheet("background: transparent;")
        overlay_layout.addWidget(overlay_icon)

        overlay_title = QLabel("松开以导入文件")
        overlay_title.setStyleSheet("color: white; font-size: 16px; font-weight: bold; background: transparent;")
        overlay_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_layout.addWidget(overlay_title)

        overlay_hint = QLabel("支持 .xml 格式的弹幕文件")
        overlay_hint.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 12px; background: transparent;")
        overlay_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_layout.addWidget(overlay_hint)

        self._drop_overlay.hide()

    def _connect_signals(self):
        # 子组件信号
        self.basic_group.file_btn.clicked.connect(self._select_file)
        self.basic_group.fetch_btn.clicked.connect(self._fetch_video_info)
        self.basic_group.part_combo.currentIndexChanged.connect(self._on_part_selected)

        # 本地信号
        self.start_btn.clicked.connect(self._toggle_task)

        # DataBinding
        self.binding.fileLoaded.connect(self._on_file_loaded)
        self.binding.fileLoadFailed.connect(self._on_file_load_failed)
        self.binding.videoFetchStarted.connect(self._on_fetch_started)
        self.binding.videoFetched.connect(self._on_fetch_succeeded)
        self.binding.videoFetchFailed.connect(self._on_fetch_failed)

        # SenderController (单任务)
        self.sender_controller.progressUpdated.connect(self._on_send_progress)
        self.sender_controller.progressUpdated.connect(self.progressUpdated.emit)
        self.sender_controller.taskFinished.connect(self._on_send_finished)

        # SenderController (队列)
        self.sender_controller.queueTaskStarted.connect(self._on_queue_task_started)
        self.sender_controller.queueTaskCompleted.connect(self._on_queue_task_completed)
        self.sender_controller.queueTaskFailed.connect(self._on_queue_task_failed)
        self.sender_controller.queueFinished.connect(self._on_queue_finished)
        self.sender_controller.queueReady.connect(lambda: self._update_queue_ui(running=False))
        self.sender_controller.queueProgressUpdated.connect(self._on_queue_progress)
        self.sender_controller.taskProgressUpdated.connect(self._on_task_progress)


        # QueueState
        self.state.queue_state.tasksChanged.connect(self._on_queue_changed)
        self.state.queue_state.taskStatusChanged.connect(self._on_queue_task_status_changed)

        # 队列按钮
        self._btn_add_to_queue.clicked.connect(self._add_to_queue)
        self._btn_start_queue.clicked.connect(self._start_queue)
        self._btn_stop_queue.clicked.connect(self._stop_queue)
        self._btn_clear_completed.clicked.connect(self._clear_completed)

    def init_bindings(self):
        """将 UI 控件与 AppState 进行双向绑定"""
        self.basic_group.init_bindings()
        self.strategy_tabs.init_bindings()

        # 监听共享数据变化（编辑器提交等场景）
        self.state.video_state.subscribe("loaded_danmakus", self._on_loaded_danmakus_changed)

    def _on_loaded_danmakus_changed(self, _value):
        """编辑器提交弹幕后自动刷新发射器 UI"""
        count = self.state.video_state.danmaku_count
        if count > 0:
            self.basic_group.file_input.setText(f"来自编辑器: {count} 条弹幕")
        else:
            self.basic_group.file_input.clear()

    def append_log(self, message: str):
        """外部调用的日志接口"""
        self.log_output.append(message)
        self.log_output.moveCursor(QTextCursor.MoveOperation.End)

    @Slot(str, int)
    def _on_file_loaded(self, filename: str, count: int):
        self.basic_group.file_input.setEnabled(True)
        if count > 0:
            self.basic_group.file_input.setText(filename)
            self.logger.info(f"✅ 文件解析成功，共 {count} 条弹幕。")
        else:
            self.basic_group.file_input.clear()
            self.logger.warning("⚠️ 文件解析完成但无有效弹幕。")

    @Slot(str, str)
    def _on_file_load_failed(self, error_msg: str, _extra: str):
        self.basic_group.file_input.setEnabled(True)
        self.basic_group.file_input.clear()
        self.logger.error(f"❌ 解析失败: {error_msg}")
        QMessageBox.critical(self, "解析失败", error_msg)


    # region Slots
    # region Slots Internal
    @Slot()
    def _select_file(self):
        """文件选择逻辑"""
        self.binding.select_file()

    @Slot()
    def _fetch_video_info(self):
        """获取视频信息"""
        raw_input = self.basic_group.bv_input.text().strip()
        if not raw_input:
            QMessageBox.warning(self, "输入错误", "请输入BV号或视频链接")
            return

        bvid = self.binding.fetch_video_info(raw_input)
        if not bvid:
            QMessageBox.warning(self, "格式错误", "未能识别有效的 BV 号。\n请检查输入内容是否正确。")
            return

        self.basic_group.bv_input.setText(bvid)

    @Slot(int)
    def _on_part_selected(self, index: int):
        """处理分P选择变化"""
        data = self.basic_group.part_combo.itemData(index)
        part_name = self.basic_group.part_combo.currentText()
        self.binding.select_part(index, data, part_name)

    @Slot()
    def _toggle_task(self):
        """开始/停止 任务"""
        if self.sender_controller.is_queue_running():
            return
        # 如果正在运行 -> 停止
        if self.sender_controller.is_running():
            self.sender_controller.stop_task()
            self._update_ui_for_state(SenderState.STOPPING)
            self.logger.info("发送器：正在请求中止...")
            return

        # 如果未运行 -> 开始
        # 校验
        status = self.sender_controller.send_status
        match status:
            case SenderStatus.EDITOR_DIRTY:
                QMessageBox.warning(self, "存在未保存的修改",
                    "检测到【弹幕编辑器】中有未应用的修改！\n\n请先返回校验器点击“应用所有修改”，\n否则发送的将是旧的、未修复的弹幕。")
                return
            case SenderStatus.NOT_READY:
                QMessageBox.warning(self, "条件不足", "请确保 BV号、分P、弹幕文件 均已就绪。")
                return
            case SenderStatus.NO_CREDENTIALS:
                QMessageBox.warning(self, "凭证缺失", "请先在账号管理页登入账号或填入 SESSDATA 和 BILI_JCT。")
                return

        # 确认对话框
        dialog = PreSendDialog(self.state, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # 锁定 UI
        self._update_ui_for_state(SenderState.RUNNING)

        state = self.state
        target = VideoTarget(
            bvid=state.video_state.bvid,
            cid=state.video_state.selected_cid,
            title=state.video_state.video_title
        )
        self.sender_controller.start_task(target, state.video_state.loaded_danmakus, state.get_api_auth(), state.sender_config)

    @Slot(QPoint)
    def _on_queue_context_menu(self, pos: QPoint):
        index = self._queue_table.indexAt(pos)
        if not index.isValid():
            return
        task = self._queue_model.get_task_at(index.row())
        if not task:
            return

        menu = QMenu(self)
        is_pending = task.status == TaskStatus.PENDING

        menu.addAction("上移", lambda: self._move_task(task.task_id, -1)).setEnabled(is_pending)
        menu.addAction("下移", lambda: self._move_task(task.task_id, 1)).setEnabled(is_pending)
        menu.addSeparator()
        menu.addAction("删除", lambda: self._remove_task(task.task_id)).setEnabled(is_pending)

        menu.exec(self._queue_table.mapToGlobal(pos))

    def _move_task(self, task_id: str, direction: int):
        self.state.queue_state.move_task(task_id, direction)

    def _remove_task(self, task_id: str):
        self.state.queue_state.remove_task(task_id)

    def _delete_selected_task(self):
        indexes = self._queue_table.selectedIndexes()
        if not indexes:
            return
        task = self._queue_model.get_task_at(indexes[0].row())
        if task and task.status == TaskStatus.PENDING:
            self._remove_task(task.task_id)

    @Slot()
    def _add_to_queue(self):
        """将当前配置添加到发送队列"""
        status = self.sender_controller.send_status
        if status == SenderStatus.NOT_READY:
            QMessageBox.warning(self, "条件不足", "请确保 BV号、分P、弹幕文件 均已就绪。")
            return
        if status == SenderStatus.NO_CREDENTIALS:
            QMessageBox.warning(self, "凭证缺失", "请先登入账号。")
            return
        if status == SenderStatus.EDITOR_DIRTY:
            QMessageBox.warning(self, "存在未保存的修改", "请先在编辑器中应用修改。")
            return

        state = self.state
        target = VideoTarget(
            bvid=state.video_state.bvid,
            cid=state.video_state.selected_cid,
            title=state.video_state.video_title,
        )
        task = QueueTask(
            target=target,
            danmakus=list(state.video_state.loaded_danmakus),
            config_snapshot=state.sender_config.model_copy(),
        )
        state.queue_state.add_task(task)
        self.logger.info(f"已添加到队列: {target.display_string} ({len(task.danmakus)} 条弹幕)")

    @Slot()
    def _start_queue(self):
        """启动队列发送"""
        if self.sender_controller.is_running() or self.sender_controller.is_queue_running():
            return
        auth_config = self.state.get_api_auth()
        if not auth_config.sessdata or not auth_config.bili_jct:
            QMessageBox.warning(self, "凭证缺失", "请先登入账号。")
            return
        if self.state.queue_state.pending_count == 0:
            QMessageBox.information(self, "队列为空", "没有待发送的任务。")
            return
        self._queue_total_dm = sum(len(t.danmakus) for t in self.state.queue_state.tasks)
        self._update_queue_ui(running=True)
        self.sender_controller.start_queue(self.state.queue_state, auth_config)

    @Slot()
    def _stop_queue(self):
        """停止队列发送"""
        if self.sender_controller.is_queue_running():
            self.sender_controller.stop_queue()
            self.logger.info("队列: 正在请求中止...")

    @Slot()
    def _clear_completed(self):
        """清除已完成的任务"""
        self.state.queue_state.clear_completed()

    # endregion
    # region Slots VideoController

    @Slot()
    def _on_fetch_started(self):
        """UI 层: 响应加载中状态"""
        self.basic_group.fetch_btn.setEnabled(False)
        self.basic_group.fetch_btn.setText("获取中")
        self.basic_group.part_combo.clear()
        self.basic_group.part_combo.setEnabled(False)

    @Slot(str, object)
    def _on_fetch_succeeded(self, bvid: str, info: VideoInfo):
        """获取成功: 填充分P下拉框"""
        self.basic_group.fetch_btn.setEnabled(True)
        self.basic_group.fetch_btn.setText("获取分P")
        self.basic_group.part_combo.setEnabled(True)

        for p in info.parts:
            if not p.cid:
                continue
            part_name = f"P{p.page} - {p.title}"
            self.basic_group.part_combo.addItem(part_name, userData={'cid': p.cid, 'duration': p.duration})
            self.state.video_state.cid_parts_map[p.cid] = part_name

        if info.parts:
            pending = self.binding.pending_part_index
            if pending is not None and 0 <= pending < self.basic_group.part_combo.count():
                self.basic_group.part_combo.setCurrentIndex(pending)
                self.logger.info(f"🔗 智能链接解析: 自动定位到第 {pending + 1} P")
            else:
                self.basic_group.part_combo.setCurrentIndex(0)
            self.binding.clear_pending_part_index()

    @Slot(str, str)
    def _on_fetch_failed(self, bvid: str, error_msg: str):
        """获取失败: 恢复 UI 状态并弹窗提示"""
        self.basic_group.fetch_btn.setEnabled(True)
        self.basic_group.fetch_btn.setText("获取分P")

        self.basic_group.part_combo.clear()
        self.basic_group.part_combo.addItem(f"获取失败，请重试")
        self.basic_group.part_combo.setEnabled(False)

        QMessageBox.warning(self, "获取失败", f"无法获取视频信息:\n{error_msg}")

    # endregion
    # region Slots SenderController

    @Slot(int, int, float)
    def _on_send_progress(self, attempted: int, total: int, eta_sec: float):
        if total > 0:
            val = int((attempted / total) * 100)
            self.progress_bar.setValue(val)

            # ETA 计算逻辑
            remaining = total - attempted
            if remaining > 0:
                duration = format_duration(eta_sec)
                finish_time = QDateTime.currentDateTime().addSecs(int(eta_sec)).toString("HH:mm:ss")
                display_text = f"%p% (剩余 {duration} | 预计 {finish_time} 结束)"
                self.progress_bar.setFormat(display_text)
                self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                self.progress_bar.setFormat("%p%")

        self.status_label.setText(f"发送中: {attempted}/{total}")

    @Slot(object)
    def _on_send_finished(self, ctx: SendingContext):
        """任务结束后的清理与保存逻辑"""
        # 恢复 UI 状态
        self._update_ui_for_state(SenderState.READY)

        if ctx and ctx.is_manually_stopped:
            self.status_label.setText("发送器：任务中止")
            self.progress_bar.setFormat("%p% (已停止)")
        else:
            self.status_label.setText("发送器：任务结束")
            self.progress_bar.setFormat("%p% (已完成)")

        if ctx:
            self._send_desktop_notification(ctx, ctx.is_manually_stopped)

            # 如果有未发出的弹幕，引导保存
            if ctx.unsent_records:
                self._prompt_save_unsent_xml(ctx.unsent_records)

    # endregion
    # region Slots Queue

    def _on_queue_changed(self):
        self._queue_model.set_tasks(self.state.queue_state.tasks)

    def _on_queue_task_status_changed(self, task_id: str, status: int):
        row = self._queue_model.get_row_by_id(task_id)
        if row >= 0:
            self._queue_model.refresh_row(row)

    @Slot(str)
    def _on_queue_task_started(self, task_id: str):
        task = self.state.queue_state.get_task_by_id(task_id)
        if task:
            task.total = len(task.danmakus)
            task.attempted = 0
            self.logger.info(f"开始发送: {task.target.display_string}")

    @Slot(str, object)
    def _on_queue_task_completed(self, task_id: str, ctx: SendingContext):
        task = self.state.queue_state.get_task_by_id(task_id)
        if task:
            self.logger.info(f"完成: {task.target.display_string} (成功 {ctx.success_count}/{ctx.total})")

    @Slot(str, str)
    def _on_queue_task_failed(self, task_id: str, error_msg: str):
        task = self.state.queue_state.get_task_by_id(task_id)
        if task:
            self.logger.error(f"失败: {task.target.display_string} - {error_msg}")

    @Slot()
    def _on_queue_finished(self):
        self.logger.info("队列执行完毕。")
        self._send_queue_notification()
        # UI 解锁延迟到 _on_queue_cleanup，避免竞态

    @Slot(int, int, float)
    def _on_queue_progress(self, current_idx: int, total: int, eta: float):
        self._queue_total = total
        self._queue_current = current_idx + 1
        self._queue_eta = eta

    @Slot(str, int, int, float)
    def _on_task_progress(self, task_id: str, attempted: int, task_total: int, eta: float):
        self._update_task_data(task_id, attempted, task_total)
        self._update_bottom_bar(attempted, task_total)

    def _update_task_data(self, task_id: str, attempted: int, task_total: int):
        """更新任务数据并刷新表格行"""
        task = self.state.queue_state.get_task_by_id(task_id)
        if task:
            task.attempted = attempted
            task.total = task_total
            row = self._queue_model.get_row_by_id(task_id)
            if row >= 0:
                self._queue_model.refresh_row(row)

    def _update_bottom_bar(self, attempted: int, task_total: int):
        """更新底部进度条（队列级 + 弹幕总数 + ETA）"""
        total_dm = self._queue_total_dm
        done_dm = self._calc_done_dm()
        pct = int((done_dm / total_dm) * 100) if total_dm > 0 else 0

        if total_dm > 0:
            self.progress_bar.setValue(pct)

        base = f"[队列 {self._queue_current}/{self._queue_total}] [弹幕 {done_dm}/{total_dm}] {pct}%"

        eta = self._queue_eta
        if eta > 0:
            duration = format_duration(eta)
            finish_time = QDateTime.currentDateTime().addSecs(int(eta)).toString("HH:mm:ss")
            self.progress_bar.setFormat(f"{base} (剩余 {duration} | 预计 {finish_time} 结束)")
        else:
            self.progress_bar.setFormat(base)

        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def _calc_done_dm(self) -> int:
        """计算全队列已处理弹幕数"""
        return sum(t.attempted for t in self.state.queue_state.tasks if t.status != TaskStatus.PENDING)

    def _send_queue_notification(self):
        queue_state = self.state.queue_state
        completed = sum(1 for t in queue_state.tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in queue_state.tasks if t.status == TaskStatus.FAILED)
        skipped = sum(1 for t in queue_state.tasks if t.status == TaskStatus.SKIPPED)
        total = len(queue_state.tasks)
        summary = f"完成: {completed} / 失败: {failed} / 跳过: {skipped} / 总计: {total}"

        if skipped > 0:
            send_windows_notification("弹幕队列已中止", summary)
        elif failed > 0:
            send_windows_notification("弹幕队列发送完毕(有失败)", summary)
        else:
            send_windows_notification("弹幕队列发送完毕", summary)

    def _update_queue_ui(self, running: bool):
        self._btn_add_to_queue.setEnabled(not running)
        self._btn_start_queue.setEnabled(not running)
        self._btn_stop_queue.setEnabled(running)
        self._btn_clear_completed.setEnabled(not running)
        if running:
            self._set_inputs_locked(True)
            self.log_output.clear()
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("%p%")
        else:
            self._set_inputs_locked(False)
            self.progress_bar.setFormat("%p%")

    # endregion
    # endregion

    def _send_desktop_notification(self, ctx: SendingContext, is_stopped: bool):
        """发送系统桌面通知"""
        title = "弹幕发送任务已结束"
        summary = f"成功: {ctx.success_count} / 尝试: {ctx.attempted_count} / 总计: {ctx.total}"

        if ctx.auto_stop_reason:
            msg = f"自动停止：{ctx.auto_stop_reason}\n{summary}"
        elif is_stopped:
            msg = f"任务已被手动停止。\n{summary}"
        elif ctx.fatal_error_occurred:
            msg = f"任务因致命错误中断！\n{summary}"
        elif ctx.total == 0:
            msg = "没有需要发送的弹幕。"
        elif ctx.success_count == ctx.attempted_count:
            msg = f"任务已完成！所有 {ctx.success_count} 条均发送成功。"
        else:
            msg = f"任务已完成。\n{summary}"

        send_windows_notification(title, msg)

    def _prompt_save_unsent_xml(self, unsent_danmakus: list[UnsentDanmakusRecord]):
        """询问并保存失败的弹幕到 XML"""
        count = len(unsent_danmakus)
        reply = QMessageBox.question(
            self, "保存失败弹幕",
            f"有 {count} 条弹幕发送失败。\n是否保存为新的 XML 文件以便重新发送？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            file_path, _ = QFileDialog.getSaveFileName(self, "保存XML", "unsent.xml", "XML Files (*.xml)")
            if file_path:
                self.logger.info(f"📥 正在保存未发送弹幕至: {file_path}")
                self.sender_controller.export_unsent_xml(
                    unsent_danmakus, file_path,
                    on_success=lambda _: self._on_export_success(file_path),
                    on_error=self._on_export_error,
                )

    @Slot(str)
    def _on_export_success(self, file_path: str):
        self.logger.info(f"✅ 未发送弹幕已保存至: {file_path}")
        QMessageBox.information(self, "保存成功", f"文件已保存至：\n{file_path}")

    @Slot(str)
    def _on_export_error(self, err: str):
        self.logger.error(f"❌ 保存XML文件失败: {err}")
        QMessageBox.critical(self, "保存失败", f"无法写入文件，请检查权限或路径。\n错误信息: {err}")


    # region UI State Management

    def _update_ui_for_state(self, state: SenderState):
        """根据任务状态统一更新 UI"""
        self.state.sender_is_active = state in (SenderState.RUNNING, SenderState.STOPPING)

        match state:
            case SenderState.READY:
                self.start_btn.setText("开始发送")
                self.start_btn.setEnabled(True)
                self._update_btn_style(False)
                self._set_inputs_locked(False)
                self.progress_bar.setFormat("%p%")

            case SenderState.RUNNING:
                self.start_btn.setText("紧急停止")
                self.start_btn.setEnabled(True)
                self._update_btn_style(True)
                self._set_inputs_locked(True)
                self.log_output.clear()
                self.progress_bar.setValue(0)

            case SenderState.STOPPING:
                self.start_btn.setText("停止中...")
                self.start_btn.setEnabled(False)
                self.progress_bar.setFormat("%p% (正在停止...)")

    # endregion

    def _update_btn_style(self, running: bool):
        """统一刷新按钮状态与图标的私有方法"""
        state = "running" if running else "ready"
        self.start_btn.setProperty("state", state)
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        self.start_btn.setIcon(self._icon_stop if running else self._icon_start)

    def _set_inputs_locked(self, locked: bool):
        """
        设置输入控件的锁定状态

        Args:
            locked (bool): True 表示锁定(不可编辑)，False 表示解锁(可编辑)。
        """
        self.basic_group.set_inputs_locked(locked)
        self.strategy_tabs.set_inputs_locked(locked)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """鼠标拖拽文件进入页面区域"""
        # 如果当前正在发送弹幕则拒绝拖入
        if self.state.sender_is_active:
            event.ignore()
            return

        if urls := event.mimeData().urls():
            # 检查是否为本地文件且后缀为XML
            if urls[0].isLocalFile() and urls[0].toLocalFile().lower().endswith('.xml'):
                event.acceptProposedAction()
                self._drop_overlay.setGeometry(self.rect())
                self._drop_overlay.show()
                self._drop_overlay.raise_()
                return

        # 拒绝其他类型文件输入
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        """鼠标拖离区域"""
        self._drop_overlay.hide()

    def dropEvent(self, event: QDropEvent) -> None:
        """鼠标落下"""
        self._drop_overlay.hide()
        # 如果当前正在发送弹幕则拒绝拖入
        if self.state.sender_is_active:
            event.ignore()
            return

        if urls := event.mimeData().urls():
            if len(urls) > 1:
                self.logger.info(f"检测到拖入 {len(urls)} 个文件，仅处理第一个。")

            file_path = urls[0].toLocalFile()
            self.logger.info(f"📥 接收到拖拽文件: {file_path}")
            self.binding.load_file(file_path)
            event.acceptProposedAction()


