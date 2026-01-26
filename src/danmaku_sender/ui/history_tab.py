import logging
from enum import IntEnum
from datetime import datetime
from functools import partial

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, 
    QPushButton, QTableView, QHeaderView, QAbstractItemView, QMenu, 
    QApplication, QDialog, QFormLayout, QFrame
)
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QBrush

from ..core.history_manager import HistoryManager, DanmakuStatus
from ..core.models.video import VideoInfo
from ..core.state import AppState
from ..core.workers import FetchInfoWorker


logger = logging.getLogger("HistoryTab")


class Col(IntEnum):
    BVID = 0
    PART = 1
    MSG = 2
    STATUS = 3
    TIME = 4


class DanmakuDetailDialog(QDialog):
    def __init__(self, record: dict, video_info: VideoInfo | None, parent= None):
        super().__init__(parent)
        self.setWindowTitle("弹幕详情档案")
        self.resize(500, 450)
        self._record = record
        self._video_info = video_info
        self._create_ui()

    def _create_ui(self):
        layout = QFormLayout(self)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        def add_row(label, value):
            lbl = QLabel(str(value))
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setWordWrap(True)
            layout.addRow(f"{label}:", lbl)

        # --- 视频元数据 ---
        layout.addRow(QLabel("<b>[ 视频信息 ]</b>"))

        cid = self._record['cid']
        bvid = self._record['bvid']

        # 尝试从 VideoInfo 对象获取分P信息
        part_idx = "未知"
        part_title = "-"
        video_title = "加载中或未知..."

        if self._video_info:
            video_title = self._video_info.title
            part = self._video_info.get_part_by_cid(cid)
            if part:
                part_idx = f"P{part.page}"
                part_title = part.title

        add_row("BVID", bvid)
        add_row("视频标题", video_title)
        add_row("分P序号", part_idx)
        add_row("分P标题", part_title)
        add_row("CID", cid)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addRow(line)

        # --- 弹幕参数 ---
        layout.addRow(QLabel("<b>[ 弹幕参数 ]</b>"))

        status_map = {
            DanmakuStatus.PENDING: "⏳ 待验证",
            DanmakuStatus.VERIFIED: "✅ 已存活",
            DanmakuStatus.LOST: "❌ 已丢失"
        }
        status = status_map.get(self._record['status'], "未知")
        if self._record.get('is_visible', 1) == 0:
            status += " (API返回屏蔽)"

        add_row("当前状态", status)
        add_row("弹幕内容", self._record['msg'])
        add_row("DmID", self._record['dmid'])
        add_row("发送时间", datetime.fromtimestamp(self._record['ctime']).strftime('%Y-%m-%d %H:%M:%S'))
        add_row("视频内时间", f"{self._record['progress']} ms")
        add_row("字号", self._record['fontsize'])
        add_row("颜色", f"#{self._record['color']:06x}")


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
    

class HistoryTab(QWidget):
    def __init__(self):
        super().__init__()
        self._state: AppState | None = None
        self._history_manager = HistoryManager()

        self._active_workers: dict[str, FetchInfoWorker] = {}
        self._fetched_bvids = set()

        self._create_ui()

    def bind_state(self, state: AppState):
        self._state = state
        self._refresh_table()

    def _create_ui(self):
        layout = QVBoxLayout(self)

        filter_layout = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索内容 / BV号 ...")
        self._search_input.returnPressed.connect(self._refresh_table)

        self._status_combo = QComboBox()
        self._status_combo.addItem("全部状态", -1)
        self._status_combo.addItem("待验证", DanmakuStatus.PENDING.value)
        self._status_combo.addItem("已存活", DanmakuStatus.VERIFIED.value)
        self._status_combo.addItem("已丢失", DanmakuStatus.LOST.value)
        self._status_combo.currentIndexChanged.connect(self._refresh_table)

        btn_refresh = QPushButton("刷新数据")
        btn_refresh.clicked.connect(self._refresh_table)

        filter_layout.addWidget(QLabel("搜索:"))
        filter_layout.addWidget(self._search_input)
        filter_layout.addWidget(QLabel("状态:"))
        filter_layout.addWidget(self._status_combo)
        filter_layout.addWidget(btn_refresh)

        layout.addLayout(filter_layout)

        # 表格
        self._table_view = QTableView()
        self._model = HistoryTableModel()
        self._table_view.setModel(self._model)

        self._table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table_view.setAlternatingRowColors(True)
        self._table_view.verticalHeader().setVisible(False)
        self._table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self._table_view.customContextMenuRequested.connect(self._on_context_menu)
        self._table_view.doubleClicked.connect(self._on_row_double_clicked)

        # 列宽
        header = self._table_view.horizontalHeader()
        header.setSectionResizeMode(Col.BVID, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(Col.PART, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(Col.MSG, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(Col.STATUS, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(Col.TIME, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self._table_view)

    def _refresh_table(self):
        keyword = self._search_input.text().strip()
        status_filter = self._status_combo.currentData()

        records = self._history_manager.query_history(keyword, status_filter)
        self._model.set_records(records)

        if self._state:
            self._fetch_missing_metadata(records)

    def _fetch_missing_metadata(self, records):
        """扫描缺失元数据的 BVID 并启动 Worker"""
        for row in records:
            bvid = row['bvid']
            if (self._model.get_video_info(bvid) is None
                and bvid not in self._fetched_bvids):
                self._start_worker(bvid)

    def _start_worker(self, bvid):
        self._fetched_bvids.add(bvid)
        self._model.mark_as_loading(bvid)
        
        if not self._state:
            return

        auth_config = self._state.get_api_auth()
        worker = FetchInfoWorker(bvid, auth_config)

        worker.finished_success.connect(partial(self._on_worker_success, bvid))
        worker.finished_error.connect(partial(self._on_worker_error, bvid))

        worker.finished.connect(partial(self._cleanup_worker, bvid, worker))

        self._active_workers[bvid] = worker
        worker.start()

    def _on_worker_success(self, bvid, video_info: VideoInfo):
        """Worker 回调：接收 VideoInfo 对象"""
        self._model.update_video_cache(bvid, video_info)

    def _on_worker_error(self, bvid, error_msg):
        """Worker 失败回调"""
        if bvid in self._fetched_bvids:
            self._fetched_bvids.remove(bvid)
        
        self._model.update_video_cache(bvid, None)

    def _cleanup_worker(self, bvid, worker: FetchInfoWorker):
        if bvid in self._active_workers:
            del self._active_workers[bvid]

        worker.deleteLater()

    def _on_row_double_clicked(self, index: QModelIndex):
        if index.isValid():
            record = self._model.get_record_at(index.row())
            if record:
                self._show_detail_dialog(record)

    def _show_detail_dialog(self, record):
        video_info = self._model.get_video_info(record['bvid'])
        dlg = DanmakuDetailDialog(record, video_info, self)
        dlg.exec()

    def _on_context_menu(self, pos):
        index = self._table_view.indexAt(pos)
        if not index.isValid():
            return
        
        record = self._model.get_record_at(index.row())
        if not record:
            return
        
        menu = QMenu(self)

        url = f"https://www.bilibili.com/video/{record['bvid']}"
        part_txt = ""

        video_info = self._model.get_video_info(record['bvid'])
        if video_info:
            part = video_info.get_part_by_cid(record['cid'])
            if part:
                url += f"?p={part.page}"
                part_txt = f"(P{part.page})"

        action_open = QAction(f"🌐 浏览器打开 {part_txt}", self)
        action_open.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        menu.addAction(action_open)

        menu.addSeparator()

        menu.addAction("📋 查看完整详情", lambda: self._show_detail_dialog(record))
        menu.addAction("复制 BVID", lambda: QApplication.clipboard().setText(record['bvid']))
        menu.addAction("复制 内容", lambda: QApplication.clipboard().setText(record['msg']))

        menu.exec(self._table_view.mapToGlobal(pos))