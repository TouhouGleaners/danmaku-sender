import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QTableView, QHeaderView, QAbstractItemView, QMenu, QApplication
)
from PySide6.QtCore import Qt, QModelIndex, QUrl, Slot, QPoint
from PySide6.QtGui import QAction, QDesktopServices

from .components import Col, HistoryTableModel
from .dialogs import DanmakuDetailDialog
from ..controllers.video_controller import VideoController
from ..controllers.history_controller import HistoryController

from ...core.database.history_manager import DanmakuStatus
from ...core.entities.video import VideoInfo
from ...core.state import AppState


logger = logging.getLogger("App.System.UI.History")


class HistoryPage(QWidget):
    def __init__(self):
        super().__init__()
        self._state: AppState | None = None
        self._fetched_bvids = set()

        self.video_controller = VideoController(self)
        self.history_controller = HistoryController(self)

        self._create_ui()
        self._connect_signals()

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

    def _connect_signals(self):
        """信号连接"""
        # VideoController
        self.video_controller.fetchSucceeded.connect(self._on_video_fetch_succeeded)
        self.video_controller.fetchFailed.connect(self._on_video_fetch_failed)

        # HistoryController
        self.history_controller.historyFetched.connect(self._on_history_query_succeeded)
        self.history_controller.errorOccurred.connect(self._on_history_query_failed)

    def bind_state(self, state: AppState):
        self._state = state
        self._refresh_table()

    def _refresh_table(self):
        """发起异步刷新请求"""
        keyword = self._search_input.text().strip()
        status_filter = self._status_combo.currentData()

        self._model.set_records([])

        self.history_controller.query(keyword, status_filter)

    def _fetch_missing_metadata(self, records):
        """扫描缺失元数据的 BVID 并推入后台队列"""
        if not self._state:
            return

        auth_config = self._state.get_api_auth()
        missing_bvids = []
        for row in records:
            bvid = row['bvid']
            if self._model.get_video_info(bvid) is None and bvid not in self._fetched_bvids:
                self._fetched_bvids.add(bvid)
                self._model.mark_as_loading(bvid)
                missing_bvids.append(bvid)

        if missing_bvids:
            self.video_controller.fetch_multiple_infos(missing_bvids, auth_config)

    def _show_detail_dialog(self, record):
        video_info = self._model.get_video_info(record['bvid'])
        dlg = DanmakuDetailDialog(record, video_info, self)
        dlg.exec()


    # region Slots
    # region Slots VideoController
    @Slot(str, VideoInfo)
    def _on_video_fetch_succeeded(self, bvid: str, video_info: VideoInfo):
        """
        B 站 API 视频详情获取成功

        将结果写入表格模型缓存，并触发当前行的高亮/重绘。
        """
        self._model.update_video_cache(bvid, video_info)

    @Slot(str, str)
    def _on_video_fetch_failed(self, bvid: str, error_msg: str):
        """
        B 站 API 视频详情获取失败 (超时或 404)

        将缓存置空，从拉取池中释放，并恢复表格默认显示。
        """
        if bvid in self._fetched_bvids:
            self._fetched_bvids.remove(bvid)
        self._model.update_video_cache(bvid, None)

    # endregion

    # region Slots HistoryController
    @Slot(list)
    def _on_history_query_succeeded(self, records: list):
        """
        本地 SQLite 查询完成回调

        将结果刷入表格，并触发缺失元数据的后台补全。
        """
        self._model.set_records(records)
        if self._state:
            self._fetch_missing_metadata(records)

    @Slot(str)
    def _on_history_query_failed(self, err_msg: str):
        """
        本地 SQLite 查询失败兜底

        通常因数据库锁定或文件损坏导致。
        """
        logger.error(f"历史记录数据库查询失败: {err_msg}")

    # endregion

    @Slot(QModelIndex)
    def _on_row_double_clicked(self, index: QModelIndex):
        if index.isValid():
            record = self._model.get_record_at(index.row())
            if record:
                self._show_detail_dialog(record)

    @Slot(QPoint)
    def _on_context_menu(self, pos: QPoint):
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

    # endregion