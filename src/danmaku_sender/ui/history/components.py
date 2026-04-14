from enum import IntEnum
from datetime import datetime

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor, QBrush

from ...core.database.history_manager import DanmakuStatus
from ...core.entities.video import VideoInfo


class Col(IntEnum):
    BVID = 0
    PART = 1
    MSG = 2
    STATUS = 3
    TIME = 4


class HistoryTableModel(QAbstractTableModel):
    HEADERS = ["BVID", "分P", "弹幕内容", "状态", "发送时间"]

    def __init__(self, parent = None):
        super().__init__(parent)
        self._records = []
        self._video_cache: dict[str, VideoInfo] = {}  # Key: BVID, Value: VideoInfo
        self._loading_bvids = set()

    def set_records(self, records):
        self.beginResetModel()
        self._records = records
        self.endResetModel()

    def mark_as_loading(self, bvid):
        self._loading_bvids.add(bvid)
        self.layoutChanged.emit()

    def update_video_cache(self, bvid: str, info: VideoInfo | None):
        if info:
            self._video_cache[bvid] = info

        if bvid in self._loading_bvids:
            self._loading_bvids.remove(bvid)

        self.layoutChanged.emit()

    def get_video_info(self, bvid: str) -> VideoInfo | None:
        return self._video_cache.get(bvid)

    def get_record_at(self, row):
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    # --- Qt Methods ---
    def rowCount(self, parent = QModelIndex()):
        return len(self._records)

    def columnCount(self, parent = QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        record = self._records[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._get_display_text(record, col)
        elif role == Qt.ItemDataRole.ForegroundRole:
            return self._get_text_color(record, col)
        elif role == Qt.ItemDataRole.ToolTipRole:
            return self._get_tooltip(record, col)

        return None

    def _get_display_text(self, record, col):
        if col == Col.BVID:
            return record['bvid']

        if col == Col.PART:
            bvid = record['bvid']
            video_info = self._video_cache.get(bvid)

            if video_info:
                part = video_info.get_part_by_cid(record['cid'])
                if part:
                    return f"P{part.page}"

            if bvid in self._loading_bvids:
                return "..."

            return f"CID: {record['cid']}"

        if col == Col.MSG:
            return record['msg']

        if col == Col.STATUS:
            status = record['status']
            if status == DanmakuStatus.VERIFIED:
                return "已存活"
            if status == DanmakuStatus.LOST:
                return "已丢失"
            return "待验证"

        if col == Col.TIME:
            return datetime.fromtimestamp(record['ctime']).strftime('%Y-%m-%d %H:%M:%S')

        return ""

    def _get_text_color(self, record, col):
        if col == Col.STATUS:
            status = record['status']
            if status == DanmakuStatus.VERIFIED:
                return QBrush(QColor("#27ae60"))
            if status == DanmakuStatus.LOST:
                return QBrush(QColor("#c0392b"))
            return QBrush(QColor("#f39c12"))
        return None

    def _get_tooltip(self, record, col):
        video_info = self._video_cache.get(record['bvid'])

        if col == Col.BVID:
            return video_info.title if video_info else "正在获取..."

        if col == Col.PART:
            if video_info:
                part = video_info.get_part_by_cid(record['cid'])
                if part:
                    return f"P{part.page} - {part.title}"
            return f"CID: {record['cid']}"

        return None