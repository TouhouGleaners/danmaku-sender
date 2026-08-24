import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QDialog,
    QGroupBox, QTextEdit, QProgressBar, QMessageBox,
    QTableView, QHeaderView, QAbstractItemView, QMenu
)
from PySide6.QtGui import QTextCursor, QShortcut, QKeySequence, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtCore import Qt, QPoint, QModelIndex, QDateTime, QEvent, QTimer, Signal, Slot

from .components import QueueTableModel
from .components.queue_table import ProgressBarDelegate
from .components.task_builder_dialog import TaskBuilderDialog
from .components.task_detail_dialog import TaskDetailDialog
from .data_binding import SenderDataBinding

from danmaku_sender.ui.framework.style_loader import SvgIcon
from danmaku_sender.controller.video_controller import VideoController
from danmaku_sender.controller.sender_controller import SenderController, SenderStatus
from danmaku_sender.service.danmaku_parser import DanmakuParser
from danmaku_sender.types.models.video import VideoInfo
from danmaku_sender.types.models.common import VideoTarget
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


    def _create_ui(self):
        # 主布局 - 垂直布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- 队列区 ---
        queue_group = QGroupBox("发送队列")
        queue_layout = QVBoxLayout(queue_group)

        self._queue_model = QueueTableModel()
        self._queue_model.on_reorder = self._on_queue_reorder
        self._queue_table = QTableView()
        self._queue_table.setModel(self._queue_model)
        self._queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._queue_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._queue_table.setAlternatingRowColors(True)
        self._queue_table.verticalHeader().setVisible(False)

        header = self._queue_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(2, 150)
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

        # 拖放外部文件到表格行
        self._queue_table.setAcceptDrops(True)
        self._queue_table.setStyleSheet("QTableView::item:selected { background: #3daee9; color: white; }")
        self._queue_table.installEventFilter(self)

        # 双击查看详情
        self._queue_table.doubleClicked.connect(self._on_queue_double_clicked)

        # 键盘删除
        QShortcut(QKeySequence.StandardKey.Delete, self._queue_table, self._delete_selected_task)

        queue_layout.addWidget(self._queue_table)

        # 空状态引导
        self._empty_hint = QLabel("队列为空  点击「新建任务」添加发送任务", self._queue_table.viewport())
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setStyleSheet("color: #888; font-size: 14px;")
        self._empty_hint.setVisible(False)
        self._queue_model.modelReset.connect(self._update_empty_hint)

        # 布局完成后再定位，避免 viewport geometry 为零
        QTimer.singleShot(0, self._update_empty_hint)

        queue_btn_layout = QHBoxLayout()

        self._btn_add_to_queue = QPushButton("新建任务")
        self._btn_add_to_queue.setIcon(SvgIcon("start.svg"))
        self._btn_add_to_queue.setFixedWidth(120)
        self._btn_add_to_queue.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_add_to_queue.setProperty("action", "true")
        self._btn_add_to_queue.setProperty("state", "ready")

        self._btn_clear_completed = QPushButton("清除已完成")
        self._btn_clear_completed.setFixedWidth(100)
        self._btn_clear_completed.setCursor(Qt.CursorShape.PointingHandCursor)

        queue_btn_layout.addWidget(self._btn_add_to_queue)
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

        self.status_label = QLabel("发送器：待命")

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        self._btn_start_queue = QPushButton("启动队列")
        self._btn_start_queue.setIcon(SvgIcon("start.svg"))
        self._btn_start_queue.setFixedWidth(100)
        self._btn_start_queue.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_start_queue.setProperty("action", "true")
        self._btn_start_queue.setProperty("state", "ready")

        self._btn_stop_queue = QPushButton("停止队列")
        self._btn_stop_queue.setIcon(SvgIcon("stop.svg"))
        self._btn_stop_queue.setFixedWidth(100)
        self._btn_stop_queue.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_stop_queue.setProperty("action", "true")
        self._btn_stop_queue.setProperty("state", "running")
        self._btn_stop_queue.setVisible(False)

        action_layout.addWidget(self.status_label)
        action_layout.addWidget(self.progress_bar, stretch=1)
        action_layout.addWidget(self._btn_start_queue)
        action_layout.addWidget(self._btn_stop_queue)

        main_layout.addLayout(action_layout)

    def _connect_signals(self):
        # 队列按钮
        self._btn_add_to_queue.clicked.connect(self._add_to_queue)
        self._btn_clear_completed.clicked.connect(self._clear_completed)
        self._btn_start_queue.clicked.connect(self._start_queue)
        self._btn_stop_queue.clicked.connect(self._stop_queue)

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

    def init_bindings(self):
        """将 UI 控件与 AppState 进行双向绑定"""
        pass

    def append_log(self, message: str):
        """外部调用的日志接口"""
        self.log_output.append(message)
        self.log_output.moveCursor(QTextCursor.MoveOperation.End)

    @Slot(QModelIndex)
    def _on_queue_double_clicked(self, index: QModelIndex):
        task = self._queue_model.get_task_at(index.row())
        if task:
            self._show_task_detail(task)

    @Slot(QPoint)
    def _on_queue_context_menu(self, pos: QPoint):
        index = self._queue_table.indexAt(pos)
        if not index.isValid():
            return
        task = self._queue_model.get_task_at(index.row())
        if not task:
            return

        menu = QMenu(self)
        is_pending = task.status in (TaskStatus.PENDING, TaskStatus.UNCONFIGURED)

        menu.addAction("查看详情/编辑配置", lambda: self._show_task_detail(task))
        menu.addSeparator()
        menu.addAction("上移", lambda: self._move_task(task.task_id, -1)).setEnabled(is_pending)
        menu.addAction("下移", lambda: self._move_task(task.task_id, 1)).setEnabled(is_pending)
        menu.addSeparator()
        menu.addAction("删除", lambda: self._remove_task(task.task_id)).setEnabled(is_pending)

        menu.exec(self._queue_table.mapToGlobal(pos))

    def _show_task_detail(self, task: QueueTask):
        """查看任务详情并可编辑配置"""
        dialog = TaskDetailDialog(task, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            task.config_snapshot = dialog.get_config()
            self.logger.info(f"已更新任务配置: {task.target.display_string}")

    def _move_task(self, task_id: str, direction: int):
        self.state.queue_state.move_task(task_id, direction)

    def _remove_task(self, task_id: str):
        self.state.queue_state.remove_task(task_id)

    def _delete_selected_task(self):
        indexes = self._queue_table.selectedIndexes()
        if not indexes:
            return
        task = self._queue_model.get_task_at(indexes[0].row())
        if task and task.status in (TaskStatus.PENDING, TaskStatus.UNCONFIGURED):
            self._remove_task(task.task_id)

    @Slot()
    def _add_to_queue(self):
        """打开任务构建弹窗"""
        dialog = TaskBuilderDialog(self.state, self)
        dialog.taskCreated.connect(self._on_task_created)
        dialog.exec()

    def _on_task_created(self, task: QueueTask):
        """弹窗创建任务后的回调"""
        self.state.queue_state.add_task(task)

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
    # region Slots Queue

    def _on_queue_reorder(self, reordered_tasks):
        """拖拽排序后同步 QueueState"""
        self.state.queue_state._tasks = reordered_tasks
        self.state.queue_state.tasksChanged.emit()

    def eventFilter(self, obj, event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> bool:
        """处理拖放到队列表格上的外部 XML 文件"""
        if obj is not self._queue_table:
            return super().eventFilter(obj, event)

        match event.type():
            case QEvent.Type.DragEnter:
                return self._on_table_drag_enter(event)
            case QEvent.Type.DragMove:
                return self._on_table_drag_move(event)
            case QEvent.Type.Drop:
                return self._on_table_drop(event)

        return super().eventFilter(obj, event)

    @staticmethod
    def _get_xml_files(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> list[str]:
        """从拖放事件中提取所有本地 XML 文件路径"""
        result = []
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith('.xml'):
                result.append(url.toLocalFile())

        return result

    def _on_table_drag_enter(self, event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> bool:
        if self.state.sender_is_active:
            return False

        if self._get_xml_files(event):
            event.acceptProposedAction()
            return True

        return False

    def _on_table_drag_move(self, event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> bool:
        if self.state.sender_is_active or not self._get_xml_files(event):
            return False

        viewport_pos = self._queue_table.viewport().mapFrom(self._queue_table, event.pos())
        index = self._queue_table.indexAt(viewport_pos)
        task = self._queue_model.get_task_at(index.row()) if index.isValid() else None

        if task and task.status in (TaskStatus.UNCONFIGURED, TaskStatus.PENDING):
            self._queue_table.selectRow(index.row())
            event.acceptProposedAction()
        else:
            self._queue_table.clearSelection()
            event.ignore()

        return True

    def _on_table_drop(self, event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> bool:
        self._queue_table.clearSelection()
        self._queue_table.unsetCursor()
        xml_files = self._get_xml_files(event)
        if not xml_files:
            return False

        viewport_pos = self._queue_table.viewport().mapFrom(self._queue_table, event.pos())
        index = self._queue_table.indexAt(viewport_pos)
        task = self._queue_model.get_task_at(index.row()) if index.isValid() else None

        if not task or task.status not in (TaskStatus.UNCONFIGURED, TaskStatus.PENDING):
            return False

        if len(xml_files) == 1:
            self._assign_file_to_task(task, xml_files[0])
        else:
            self._assign_files_to_pending(xml_files, index.row())
        event.accept()

        return True

    def _assign_files_to_pending(self, file_paths: list[str], start_row: int = 0):
        """将多个 XML 文件从指定行开始按顺序分配给可配置的任务"""
        tasks = self.state.queue_state.tasks
        pending_from_start = [
            t for t in tasks[start_row:]
            if t.status in (TaskStatus.UNCONFIGURED, TaskStatus.PENDING)
        ]
        for i, file_path in enumerate(file_paths):
            if i >= len(pending_from_start):
                break
            self._assign_file_to_task(pending_from_start[i], file_path)

    def _assign_file_to_task(self, task: QueueTask, file_path: str):
        """解析 XML 并分配弹幕给指定任务"""
        parser = DanmakuParser()
        try:
            danmakus = parser.parse_xml_file(file_path)
        except Exception as e:
            self.logger.error(f"弹幕文件解析失败: {e}")
            return

        if not danmakus:
            self.logger.warning("弹幕文件为空。")
            return
        task.danmakus = danmakus
        task.total = len(danmakus)
        self.state.queue_state.update_task_status(task.task_id, TaskStatus.PENDING)
        self.logger.info(f"已分配弹幕: {task.target.display_string} ({len(danmakus)} 条)")

    def _update_empty_hint(self):
        self._empty_hint.setVisible(self._queue_model.rowCount() == 0)
        self._reposition_empty_hint()

    def _reposition_empty_hint(self):
        self._empty_hint.setGeometry(self._queue_table.viewport().rect())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_empty_hint()

    def _on_queue_changed(self):
        self._queue_model.set_tasks(self.state.queue_state.tasks)

    def _on_queue_task_status_changed(self, task_id: str, status: str):
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
        """计算全队列已处理弹幕数（不含 PENDING 和 PAUSED）"""
        return sum(t.attempted for t in self.state.queue_state.tasks if t.status not in (TaskStatus.PENDING, TaskStatus.PAUSED))

    def _send_queue_notification(self):
        queue_state = self.state.queue_state
        completed = sum(1 for t in queue_state.tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in queue_state.tasks if t.status == TaskStatus.FAILED)
        paused = sum(1 for t in queue_state.tasks if t.status == TaskStatus.PAUSED)
        skipped = sum(1 for t in queue_state.tasks if t.status == TaskStatus.SKIPPED)
        total = len(queue_state.tasks)
        summary = f"完成: {completed} / 失败: {failed} / 暂停: {paused} / 跳过: {skipped} / 总计: {total}"

        if paused > 0:
            send_windows_notification("弹幕队列已暂停", f"{summary}\n暂停的任务可重新启动继续发送。")
        elif skipped > 0:
            send_windows_notification("弹幕队列已中止", summary)
        elif failed > 0:
            send_windows_notification("弹幕队列发送完毕(有失败)", summary)
        else:
            send_windows_notification("弹幕队列发送完毕", summary)

    def _update_queue_ui(self, running: bool):
        self._btn_add_to_queue.setEnabled(not running)
        self._btn_clear_completed.setEnabled(not running)
        self._queue_model.queue_running = running

        # 底部按钮切换
        self._btn_start_queue.setVisible(not running)
        self._btn_stop_queue.setVisible(running)

        if running:
            self.log_output.clear()
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("%p%")

    # endregion
    # endregion
