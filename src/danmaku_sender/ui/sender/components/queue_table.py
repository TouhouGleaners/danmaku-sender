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

    def refresh(self):
        """通知视图数据已变更（状态更新等场景）"""
        self.layoutChanged.emit()

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

        if role == Qt.ItemDataRole.DisplayRole:
            return self._get_display(task, col)
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._get_color(task, col)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._get_tooltip(task, col)

        return None

    def _get_display(self, task: QueueTask, col: int) -> str:
        if col == QueueCol.INDEX:
            return str(self._tasks.index(task) + 1)
        if col == QueueCol.TITLE:
            return task.target.title or task.target.bvid
        if col == QueueCol.PART:
            return f"CID: {task.target.cid}"
        if col == QueueCol.COUNT:
            return str(len(task.danmakus))
        if col == QueueCol.STATUS:
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
