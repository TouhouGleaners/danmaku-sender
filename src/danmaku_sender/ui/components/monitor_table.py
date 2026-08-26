"""监视器表格模型 - 用于显示队列任务的监视状态"""

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor

from danmaku_sender.types.models.common import MonitorStats
from danmaku_sender.types.models.queue import QueueTask


class QueueMonitorModel(QAbstractTableModel):
    """队列监视表格模型"""

    HEADERS = ["任务", "状态", "已发送", "已存活", "待验证", "疑似丢失"]

    def __init__(self):
        super().__init__()
        self._data: list[dict] = []

    def update_data(self, tasks: list[QueueTask], stats_map: dict[str, MonitorStats]):
        """更新表格数据

        Args:
            tasks: 队列任务列表
            stats_map: 任务ID -> 统计数据 的映射
        """
        self.beginResetModel()
        self._data = []
        for task in tasks:
            stats = stats_map.get(task.task_id, {'total': 0, 'verified': 0, 'pending': 0, 'lost': 0})
            self._data.append({
                'name': task.target.display_string,
                'status': task.status.value,
                'total': stats.get('total', 0),
                'verified': stats.get('verified', 0),
                'pending': stats.get('pending', 0),
                'lost': stats.get('lost', 0),
            })
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if row >= len(self._data):
            return None

        item = self._data[row]

        if role == Qt.ItemDataRole.DisplayRole:
            key = ['name', 'status', 'total', 'verified', 'pending', 'lost'][col]
            return str(item[key])
        elif role == Qt.ItemDataRole.ForegroundRole:
            # 丢失数为红色
            if col == 5 and item['lost'] > 0:
                return QColor("#c0392b")
            # 存活数为绿色
            if col == 3 and item['verified'] > 0:
                return QColor("#27ae60")
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None
