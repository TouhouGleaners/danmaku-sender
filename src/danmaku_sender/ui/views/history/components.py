"""历史页弹幕表模型：行数据以角色形式提供，显示文本与状态色按列语义生成。"""
from datetime import datetime
from enum import IntEnum
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt

from danmaku_sender.types.models.common import DanmakuStatus
from danmaku_sender.types.models.video import VideoInfo


class Col(IntEnum):
    """弹幕表的列序。"""

    BVID = 0
    PART = 1
    MSG = 2
    STATUS = 3
    TIME = 4


class HistoryTableModel(QAbstractTableModel):
    """弹幕历史的表模型。

    Attributes:
        HEADERS (list[str]): 表头文字，按列序排列。
        ROW_ROLE_NAMES (tuple[bytes, ...]): 行级角色名，供 QML 行委托按行取值。

    Typical usage example::

        model = HistoryTableModel(self)
        model.set_records(records)
        model.update_video_cache(bvid, video_info)
    """

    HEADERS = ["BVID", "分P", "弹幕内容", "状态", "发送时间"]

    ROW_ROLE_NAMES = (b"bvid", b"part", b"msg", b"status", b"time", b"statusTone")

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._records: list[dict] = []
        self._video_cache: dict[str, VideoInfo] = {}
        self._loading_bvids: set[str] = set()

    def set_records(self, records: list[dict]) -> None:
        """整体替换弹幕记录行。

        Args:
            records (list[dict]): 弹幕历史记录行。
        """
        self.beginResetModel()
        self._records = records
        self.endResetModel()

    def mark_as_loading(self, bvid: str) -> None:
        """标记 BVID 的视频信息正在获取。

        Args:
            bvid (str): 视频 BVID。
        """
        self._loading_bvids.add(bvid)
        self.layoutChanged.emit()

    def update_video_cache(self, bvid: str, info: VideoInfo | None) -> None:
        """写入视频信息缓存并清除该 BVID 的加载标记。

        Args:
            bvid (str): 视频 BVID。
            info (VideoInfo | None): 视频信息；None 表示获取失败。
        """
        if info:
            self._video_cache[bvid] = info

        if bvid in self._loading_bvids:
            self._loading_bvids.remove(bvid)

        self.layoutChanged.emit()

    def get_video_info(self, bvid: str) -> VideoInfo | None:
        """取视频信息缓存。

        Args:
            bvid (str): 视频 BVID。

        Returns:
            VideoInfo | None: 缓存中的视频信息；未缓存时为 None。
        """
        return self._video_cache.get(bvid)

    def get_record_at(self, row: int) -> dict | None:
        """取行对应的弹幕记录。

        Args:
            row (int): 行号。

        Returns:
            dict | None: 弹幕历史记录行；非法行返回 None。
        """
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    # --- Qt Methods ---
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """返回记录行数。"""
        return len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """返回列数，即表头长度。"""
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int) -> str | None:
        """返回横向表头文字。

        Args:
            section (int): 列序。
            orientation (Qt.Orientation): 表头方向。
            role (int): 数据角色。

        Returns:
            str | None: 表头文字；非横向 DisplayRole 返回 None。
        """
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """返回单元格数据。

        Args:
            index (QModelIndex): 模型索引。
            role (int): 数据角色。

        Returns:
            Any: 显示文本、提示文本或行级角色值；不适用时为 None。
        """
        if not index.isValid():
            return None

        record = self._records[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._get_display_text(record, col)
        elif role == Qt.ItemDataRole.ToolTipRole:
            return self._get_tooltip(record, col)

        offset = role - (Qt.ItemDataRole.UserRole + 1)
        if 0 <= offset < len(Col):
            return self._get_display_text(record, offset)
        if offset == len(Col):
            return self._status_tone(record)

        return None

    def roleNames(self) -> dict[int, bytes]:
        """返回行级角色名表，键为角色号、值为角色名。"""
        return {
            Qt.ItemDataRole.UserRole + 1 + offset: name
            for offset, name in enumerate(self.ROW_ROLE_NAMES)
        }

    def _get_display_text(self, record: dict, col: int) -> str:
        """返回单元格显示文本。

        Args:
            record (dict): 弹幕历史记录行。
            col (int): 列序。

        Returns:
            str: 显示文本。
        """
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

    def _status_tone(self, record: dict) -> str:
        """取状态的健康档位。

        Args:
            record (dict): 弹幕历史记录行。

        Returns:
            str: 已存活为 good、待验证为 warn、已丢失为 bad。
        """
        status = record['status']
        if status == DanmakuStatus.VERIFIED:
            return "good"
        if status == DanmakuStatus.LOST:
            return "bad"
        return "warn"

    def _get_tooltip(self, record: dict, col: int) -> str | None:
        """返回单元格提示文本。

        Args:
            record (dict): 弹幕历史记录行。
            col (int): 列序。

        Returns:
            str | None: 提示文本；不适用时为 None。
        """
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
