from enum import IntEnum

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QBrush, QColor

from danmaku_sender.types.models.queue import QueueTask, TaskStatus


class QueueCol(IntEnum):
    INDEX = 0
    TITLE = 1
    PART = 2
    COUNT = 3
    STATUS = 4


class QueueTableModel(QAbstractTableModel):
    HEADERS = ["序号", "视频标题", "分P", "弹幕数", "状态"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: list[QueueTask] = []

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
                return self._get_display(task, col, index.row())
            case Qt.ItemDataRole.ForegroundRole:
                return self._get_color(task, col)
            case Qt.ItemDataRole.ToolTipRole:
                return self._get_tooltip(task, col)

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
