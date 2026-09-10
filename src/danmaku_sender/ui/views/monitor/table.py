"""监视器表格模型 - 用于显示队列任务的监视状态"""

from enum import IntEnum

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor

from danmaku_sender.types.models.common import MonitorStats
from danmaku_sender.types.models.queue import QueueTask


class Column(IntEnum):
    """表格列索引"""
    SEQ = 0
    TARGET = 1
    TOTAL = 2
    VERIFIED = 3
    PENDING = 4
    LOST = 5
    RATE = 6


class QueueMonitorModel(QAbstractTableModel):
    """队列监视表格模型"""

    HEADERS = ["序号", "目标视频", "已发送", "已存活", "待验证", "疑似丢失", "存活率"]
    _DEFAULT_STATS: MonitorStats = {'total': 0, 'verified': 0, 'pending': 0, 'lost': 0}

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
        self._data = [self._build_row(i, task, stats_map) for i, task in enumerate(tasks)]
        self.endResetModel()

    def _build_row(self, index: int, task: QueueTask, stats_map: dict) -> dict:
        """构建单行数据"""
        stats: MonitorStats = stats_map.get(task.task_id, self._DEFAULT_STATS)
        total = stats.get('total', 0)
        verified = stats.get('verified', 0)

        return {
            'seq': index + 1,
            'name': self._format_target(task),
            'tooltip': self._format_tooltip(task),
            'total': total,
            'verified': verified,
            'pending': stats.get('pending', 0),
            'lost': stats.get('lost', 0),
            'rate': f"{verified / total:.0%}" if total > 0 else "-",
        }

    @staticmethod
    def _format_target(task: QueueTask) -> str:
        """目标视频列：视频标题 + 分P标题"""
        parts = [task.target.display_string]
        if task.p_title:
            parts.append(task.p_title)
        return " - ".join(parts)

    @staticmethod
    def _format_tooltip(task: QueueTask) -> str:
        """完整定位信息：视频标题、任务状态、BV号、分P、CID"""
        lines = [
            task.target.display_string,
            f"状态: {task.status.value}",
            f"BV号: {task.target.bvid}",
        ]
        if task.p_title:
            lines.append(f"分P: {task.p_title}")
        lines.append(f"CID: {task.target.cid}")
        return "\n".join(lines)

    # --- Qt Model 接口 ---

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._data):
            return None

        item = self._data[index.row()]
        col = Column(index.column())

        match role:
            case Qt.ItemDataRole.DisplayRole:
                return self._get_display_text(item, col)
            case Qt.ItemDataRole.TextAlignmentRole:
                return self._get_alignment(col)
            case Qt.ItemDataRole.ToolTipRole:
                return item['tooltip'] if col == Column.TARGET else None
            case Qt.ItemDataRole.ForegroundRole:
                return self._get_color(item, col)

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    # --- 数据提取辅助方法 ---

    @staticmethod
    def _get_display_text(item: dict, col: Column) -> str:
        """获取单元格显示文本"""
        key_map = {
            Column.SEQ: 'seq',
            Column.TARGET: 'name',
            Column.TOTAL: 'total',
            Column.VERIFIED: 'verified',
            Column.PENDING: 'pending',
            Column.LOST: 'lost',
            Column.RATE: 'rate',
        }
        key = key_map.get(col)
        return str(item[key]) if key else ""

    @staticmethod
    def _get_alignment(col: Column) -> int:
        """获取单元格对齐方式"""
        if col == Column.TARGET:
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return int(Qt.AlignmentFlag.AlignCenter)

    @staticmethod
    def _get_color(item: dict, col: Column):
        """获取单元格前景色"""
        match col:
            case Column.LOST if item['lost'] > 0:
                return QColor("#c0392b")  # 红色
            case Column.VERIFIED if item['verified'] > 0:
                return QColor("#27ae60")  # 绿色
            case Column.PENDING if item['pending'] > 0:
                return QColor("#f39c12")  # 橙色
        return None
