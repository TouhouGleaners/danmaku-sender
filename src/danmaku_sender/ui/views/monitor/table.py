"""监视器表格模型 - 显示核销目标的存活统计"""

from dataclasses import dataclass
from enum import IntEnum

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from danmaku_sender.types.models.common import MonitorStats


@dataclass(frozen=True)
class MonitorRow:
    """表格一行 = 一个核销目标（数据库里有存证的 (bvid, cid)）。

    ``name`` / ``status`` 是 UI 从队列反查到的上下文，查不到就退化显示
    （bvid/cid、"—"）——核销本身不需要它们。
    """

    bvid: str
    cid: int
    name: str
    status: str
    stats: MonitorStats


class Column(IntEnum):
    """表格列索引"""
    SEQ = 0
    TARGET = 1
    STATUS = 2
    TOTAL = 3
    VERIFIED = 4
    PENDING = 5
    LOST = 6
    RATE = 7


class QueueMonitorModel(QAbstractTableModel):
    """队列监视表格模型（纯渲染：行由页面拼装）"""

    HEADERS = ["序号", "目标视频", "状态", "已发送", "已存活", "待验证", "疑似丢失", "存活率"]

    def __init__(self):
        super().__init__()
        self._data: list[MonitorRow] = []

    def update_data(self, rows: list[MonitorRow]):
        """整体替换表格行（行序 = 页面给出的顺序）"""
        self.beginResetModel()
        self._data = list(rows)
        self.endResetModel()

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
                return self._get_display_text(item, col, index.row())
            case Qt.ItemDataRole.TextAlignmentRole:
                return self._get_alignment(col)
            case Qt.ItemDataRole.ToolTipRole:
                return self._format_tooltip(item) if col == Column.TARGET else None
            case Qt.ItemDataRole.ForegroundRole:
                return self._get_color(item, col)

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    # --- 数据提取辅助方法 ---

    @staticmethod
    def _get_display_text(item: MonitorRow, col: Column, row: int) -> str:
        """获取单元格显示文本"""
        total = item.stats.get("total", 0)
        verified = item.stats.get("verified", 0)
        match col:
            case Column.SEQ:
                return str(row + 1)
            case Column.TARGET:
                return item.name
            case Column.STATUS:
                return item.status
            case Column.TOTAL:
                return str(total)
            case Column.VERIFIED:
                return str(verified)
            case Column.PENDING:
                return str(item.stats.get("pending", 0))
            case Column.LOST:
                return str(item.stats.get("lost", 0))
            case Column.RATE:
                return f"{verified / total:.0%}" if total > 0 else "-"
        return ""

    @staticmethod
    def _get_alignment(col: Column) -> int:
        """获取单元格对齐方式"""
        if col == Column.TARGET:
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return int(Qt.AlignmentFlag.AlignCenter)

    @staticmethod
    def _format_tooltip(item: MonitorRow) -> str:
        """完整定位信息：标签、BV号、CID"""
        lines = [item.name, f"BV号: {item.bvid}", f"CID: {item.cid}"]
        return "\n".join(lines)

    @staticmethod
    def _get_color(item: MonitorRow, col: Column):
        """获取单元格前景色"""
        match col:
            case Column.LOST if item.stats.get("lost", 0) > 0:
                return QColor("#c0392b")  # 红色
            case Column.VERIFIED if item.stats.get("verified", 0) > 0:
                return QColor("#27ae60")  # 绿色
            case Column.PENDING if item.stats.get("pending", 0) > 0:
                return QColor("#f39c12")  # 橙色
        return None
