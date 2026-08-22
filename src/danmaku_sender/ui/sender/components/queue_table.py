from enum import IntEnum
from typing import Callable

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSize, QMimeData
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionProgressBar, QStyleOptionViewItem, QStyle, QApplication

from danmaku_sender.types.models.queue import QueueTask, TaskStatus


class QueueCol(IntEnum):
    INDEX = 0
    TITLE = 1
    PART = 2
    COUNT = 3
    STATUS = 4
    PROGRESS = 5


class ProgressBarDelegate(QStyledItemDelegate):
    """在表格单元格中绘制进度条"""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        task: QueueTask | None = index.data(Qt.ItemDataRole.UserRole)
        if task is None:
            return super().paint(painter, option, index)

        progress = int((task.attempted / task.total) * 100) if task.total > 0 else 0

        bar = QStyleOptionProgressBar()
        bar.rect = option.rect
        bar.minimum = 0
        bar.maximum = 100
        bar.progress = progress
        bar.text = f"{task.attempted}/{task.total}" if task.total > 0 else ""
        bar.textVisible = True

        match task.status:
            case TaskStatus.COMPLETED:
                if task.attempted >= task.total:
                    bar.progress = 100
                    bar.text = f"{task.total}/{task.total}"
                else:
                    bar.text = f"{task.attempted}/{task.total}"
            case TaskStatus.FAILED:
                bar.text = "失败"
            case TaskStatus.SKIPPED:
                bar.text = "跳过"
            case TaskStatus.PENDING:
                bar.text = "等待"

        QApplication.style().drawControl(QStyle.ControlElement.CE_ProgressBar, bar, painter)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(120, 24)


class QueueTableModel(QAbstractTableModel):
    HEADERS = ["序号", "视频标题", "分P", "弹幕数", "状态", "进度"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: list[QueueTask] = []
        self.on_reorder: Callable[[list[QueueTask]], None] | None = None

    def set_tasks(self, tasks: list[QueueTask]):
        self.beginResetModel()
        self._tasks = tasks
        self.endResetModel()

    def refresh_row(self, row: int):
        """通知视图单行数据已变更（状态更新等场景）"""
        if 0 <= row < len(self._tasks):
            left = self.index(row, 0)
            right = self.index(row, len(self.HEADERS) - 1)
            self.dataChanged.emit(left, right)

    def refresh(self):
        """通知视图全量数据已变更"""
        self.layoutChanged.emit()

    def get_row_by_id(self, task_id: str) -> int:
        """按 task_id 查找行号，未找到返回 -1"""
        for i, task in enumerate(self._tasks):
            if task.task_id == task_id:
                return i
        return -1

    def get_task_at(self, row: int) -> QueueTask | None:
        if 0 <= row < len(self._tasks):
            return self._tasks[row]
        return None

    # --- Qt Methods ---

    def rowCount(self, parent=QModelIndex()):
        return len(self._tasks)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        task = self._tasks[index.row()]
        col = index.column()

        match role:
            case Qt.ItemDataRole.DisplayRole:
                if col == QueueCol.PROGRESS:
                    return None  # Delegate 接管绘制
                return self._get_display(task, col, index.row())
            case Qt.ItemDataRole.ForegroundRole:
                return self._get_color(task, col)
            case Qt.ItemDataRole.ToolTipRole:
                return self._get_tooltip(task, col)
            case Qt.ItemDataRole.UserRole:
                if col == QueueCol.PROGRESS:
                    return task  # 传递完整 task 给 Delegate

        return None

    def _get_display(self, task: QueueTask, col: int, row: int) -> str:
        match col:
            case QueueCol.INDEX:
                return str(row + 1)
            case QueueCol.TITLE:
                return task.target.title or task.target.bvid
            case QueueCol.PART:
                return f"CID: {task.target.cid}"
            case QueueCol.COUNT:
                return str(len(task.danmakus))
            case QueueCol.STATUS:
                return self._status_text(task.status)
        return ""

    def _get_color(self, task: QueueTask, col: int):
        if col == QueueCol.STATUS:
            return QBrush({
                TaskStatus.PENDING: QColor("#f39c12"),
                TaskStatus.RUNNING: QColor("#3498db"),
                TaskStatus.COMPLETED: QColor("#27ae60"),
                TaskStatus.FAILED: QColor("#c0392b"),
                TaskStatus.SKIPPED: QColor("#95a5a6"),
            }.get(task.status, QColor("#f39c12")))
        return None

    def _get_tooltip(self, task: QueueTask, col: int):
        if col == QueueCol.STATUS and task.error_msg:
            return task.error_msg
        return None

    @staticmethod
    def _status_text(status: TaskStatus) -> str:
        return {
            TaskStatus.PENDING: "等待中",
            TaskStatus.RUNNING: "执行中",
            TaskStatus.COMPLETED: "已完成",
            TaskStatus.FAILED: "失败",
            TaskStatus.SKIPPED: "已跳过",
        }.get(status, "未知")

    # --- 拖拽排序 ---

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        default = super().flags(index)
        task = self._tasks[index.row()]
        if task.status == TaskStatus.PENDING:
            return default | Qt.ItemFlag.ItemIsDragEnabled
        return default

    def mimeTypes(self) -> list[str]:
        return ["application/x-queue-task-row"]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:
        rows = sorted(set(idx.row() for idx in indexes))
        mime = QMimeData()
        mime.setText(",".join(str(r) for r in rows))
        return mime

    def dropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int, col: int, parent: QModelIndex) -> bool:
        if action != Qt.DropAction.MoveAction:
            return False

        raw = data.text()
        if not raw:
            return False

        try:
            source_rows = [int(r) for r in raw.split(",")]
        except ValueError:
            return False

        if not source_rows:
            return False

        # 只允许拖动 PENDING 任务
        for r in source_rows:
            if r >= len(self._tasks) or self._tasks[r].status != TaskStatus.PENDING:
                return False

        dest_row = row if row >= 0 else parent.row()
        if dest_row < 0:
            dest_row = len(self._tasks)

        # 只能插入到 PENDING 区域或队列末尾
        if dest_row < len(self._tasks) and self._tasks[dest_row].status != TaskStatus.PENDING:
            return False

        moved = [self._tasks[r] for r in source_rows]
        remaining = [t for i, t in enumerate(self._tasks) if i not in source_rows]

        offset = sum(1 for r in source_rows if r < dest_row)
        insert_at = dest_row - offset

        reordered = remaining[:insert_at] + moved + remaining[insert_at:]

        # 委托给上层同步 QueueState
        if self.on_reorder:
            self.on_reorder(reordered)
        else:
            self.beginResetModel()
            self._tasks = reordered
            self.endResetModel()

        return True
