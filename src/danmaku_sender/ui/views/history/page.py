"""弹幕历史页：任务时间树与弹幕表的搭建与信号连接。"""
import logging
from pathlib import Path

from PySide6.QtCore import QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from danmaku_sender.config import Settings
from danmaku_sender.controller.history_controller import HistoryController
from danmaku_sender.controller.video_controller import VideoController
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.state import AppState
from danmaku_sender.types.models.common import (
    DanmakuStatus,
    MonitorStats,
    TaskRecordRow,
    VerifyResult,
)
from danmaku_sender.types.models.video import VideoInfo
from danmaku_sender.ui.framework.column_spec import ColumnSpec
from danmaku_sender.ui.framework.qml_host import QmlWindowHost
from danmaku_sender.ui.framework.tree_model import TreeRowsModel

from .bridge import HistoryBridge
from .components import HistoryTableModel
from .dialogs import DanmakuDetailDialog
from .tree import TaskTreeBuilder

logger = logging.getLogger(__name__)

SPLIT_AREA_QML = Path(__file__).with_name("SplitArea.qml")

# 时间树的列规格；弹性列在首位，标签列在末尾连续并聚拢行右缘；数量是元数据，走小号次要文字不套标签。
TREE_COLUMNS = (
    ColumnSpec(role="label", width=None, sub_role="sublabel"),
    ColumnSpec(role="sent", width=48, align="right"),
    ColumnSpec(role="rate", align="right", tag=True, tone_role="rateTone"),
)

# 弹幕表的列规格；弹幕内容为弹性列，状态列渲染为小标签。
TABLE_COLUMNS = (
    ColumnSpec(role="msg", title="弹幕内容", width=None),
    ColumnSpec(role="status", title="状态", width=64, tag=True, tone_role="statusTone"),
    ColumnSpec(role="time", title="发送时间", width=130),
)

# 状态筛选下拉项到查询值的映射（与 QML 的 ComboBox 顺序一致）
STATUS_FILTER_VALUES = (
    -1,
    DanmakuStatus.PENDING.value,
    DanmakuStatus.VERIFIED.value,
    DanmakuStatus.LOST.value,
)


class HistoryPage(QWidget):
    """弹幕历史页：左侧任务时间树定位，右侧按选中任务展示弹幕表。

    Args:
        state (AppState): 应用状态。
        settings (Settings): 应用配置。
        history_manager (HistoryManager): 弹幕账本。
    """

    def __init__(self, state: AppState, settings: Settings, history_manager: HistoryManager) -> None:
        super().__init__()
        self.state = state
        self.settings = settings
        self._fetched_bvids: set[str] = set()
        self._current_task_id: str | None = None
        self._search_text = ""
        self._status_value = -1
        self._query_seq = 0
        self._task_seq = 0
        self._picked_record: dict | None = None
        self._tasks: list[TaskRecordRow] = []
        self._stats: dict[str, MonitorStats] = {}

        self.video_controller = VideoController(state, settings, self)
        self.history_controller = HistoryController(state, settings, history_manager, self)

        self._create_ui()
        self._connect_signals()

    def _create_ui(self) -> None:
        """搭建 QML 分栏区与数据模型。"""
        self._bridge = HistoryBridge(self)
        self._tree_rows = TreeRowsModel(("label", "sublabel", "sent", "rate", "rateTone"), self)
        self._model = HistoryTableModel(self)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QmlWindowHost(
                SPLIT_AREA_QML,
                properties={
                    "bridge": self._bridge,
                    "treeRows": self._tree_rows,
                    "records": self._model,
                    "treeColumns": ColumnSpec.to_qml_columns(
                        self._tree_rows, TREE_COLUMNS,
                        require_fill_first=True, require_trailing_tags=True,
                    ),
                    "tableColumns": ColumnSpec.to_qml_columns(self._model, TABLE_COLUMNS),
                },
                parent=self,
            )
        )

    def _connect_signals(self):
        """信号连接"""
        # VideoController
        self.video_controller.fetchSucceeded.connect(self._on_video_fetch_succeeded)
        self.video_controller.fetchFailed.connect(self._on_video_fetch_failed)

        # HistoryController
        self.history_controller.historyFetched.connect(self._on_history_query_succeeded)
        self.history_controller.historyFailed.connect(self._on_history_failed)
        self.history_controller.tasksFetched.connect(self._on_tasks_fetched)
        self.history_controller.tasksFailed.connect(self._on_tasks_failed)
        self.history_controller.verifyCompleted.connect(self._on_verify_completed)
        self.history_controller.verifyFailed.connect(self._on_verify_failed)

        # 历史页 QML 场景
        self._bridge.treeRowPicked.connect(self._on_tree_row_picked)
        self._bridge.searchSubmitted.connect(self._on_search_submitted)
        self._bridge.statusSelected.connect(self._on_status_selected)
        self._bridge.refreshRequested.connect(self._refresh_data)
        self._bridge.verifyAllRequested.connect(self._verify_all)
        self._bridge.recordPicked.connect(self._on_record_picked)
        self._bridge.openRecordRequested.connect(self._open_record)
        self._bridge.openBrowserRequested.connect(self._open_in_browser)
        self._bridge.verifyPartRequested.connect(self._on_verify_part)
        self._bridge.copyBvidRequested.connect(self._copy_bvid)
        self._bridge.copyContentRequested.connect(self._copy_content)

    def init_bindings(self) -> None:
        """载入任务清单与弹幕表初始数据。"""
        self._task_seq = self.history_controller.load_tasks()
        self._refresh_table()

    @Slot()
    def _refresh_table(self):
        """刷新弹幕表；未选中任务时清空并跳过查询；空态回到「无记录」提示。"""
        self._bridge.set_empty("暂无弹幕记录", "在左侧选择一个任务查看它的弹幕")
        self._model.set_records([])
        if self._current_task_id is None:
            return
        self._query_seq = self.history_controller.query(self._search_text, self._status_value, self._current_task_id)

    @Slot()
    def _refresh_data(self) -> None:
        """刷新任务清单、存活统计与弹幕表。"""
        self._task_seq = self.history_controller.load_tasks()
        self._refresh_table()

    @Slot(str)
    def _on_search_submitted(self, text: str) -> None:
        """搜索提交后按关键词刷新。"""
        self._search_text = text
        self._refresh_table()

    @Slot(int)
    def _on_status_selected(self, index: int) -> None:
        """状态筛选变更后刷新。"""
        if 0 <= index < len(STATUS_FILTER_VALUES):
            self._status_value = STATUS_FILTER_VALUES[index]
        self._refresh_table()

    @Slot(int)
    def _on_tree_row_picked(self, row: int) -> None:
        """选中任务后加载该任务的弹幕；分组节点仅用于展开，不更新右侧内容。"""
        payload = self._tree_rows.payload_at(row)
        if payload is None:
            return
        record, stats = payload
        self._current_task_id = record['task_id']
        self._show_task_identity(record, stats)
        self._refresh_table()

    def _show_task_identity(self, record: TaskRecordRow, stats: MonitorStats | None) -> None:
        """把选中任务的身份与存活汇总写进顶部统计卡片。

        Args:
            record (TaskRecordRow): 任务记录行。
            stats (MonitorStats | None): 存活统计；None 按零值处理。
        """
        head = f"{record['bvid']}  {record['video_title'] or ''}".rstrip()
        _, part = TaskTreeBuilder.task_labels(record)
        if stats is None:
            stats = MonitorStats(total=0, verified=0, pending=0, lost=0)

        total = stats['total']
        rate = f"{stats['verified'] / total:.0%}" if total > 0 else "-"
        self._bridge.set_summary(
            head,
            part,
            rate,
            [
                {"label": "已发送", "value": str(total)},
                {"label": "已存活", "value": str(stats['verified'])},
                {"label": "待验证", "value": str(stats['pending'])},
                {"label": "已丢失", "value": str(stats['lost'])},
            ],
        )

    @Slot(int, object)
    def _on_tasks_fetched(self, seq: int, payload: tuple[list[TaskRecordRow], dict[str, MonitorStats]]):
        """任务清单与存活统计到货，重建时间树并刷新统计卡片；早于当前请求的结果丢弃。"""
        if seq < self._task_seq:
            return
        self._tasks, self._stats = payload
        self._tree_rows.set_roots(TaskTreeBuilder.build(self._tasks, self._stats))
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        """按当前任务标识刷新统计卡片。"""
        if self._current_task_id is None:
            return
        record = next((row for row in self._tasks if row['task_id'] == self._current_task_id), None)
        if record is not None:
            self._show_task_identity(record, self._stats.get(self._current_task_id))

    def _fetch_missing_metadata(self, records):
        """扫描缺失元数据的 BVID 并推入后台队列"""
        missing_bvids = []
        for row in records:
            bvid = row['bvid']
            if self._model.get_video_info(bvid) is None and bvid not in self._fetched_bvids:
                self._fetched_bvids.add(bvid)
                self._model.mark_as_loading(bvid)
                missing_bvids.append(bvid)

        if missing_bvids:
            self.video_controller.fetch_multiple_infos(missing_bvids)

    def _show_detail_dialog(self, record: dict) -> None:
        """打开弹幕详情对话框。

        Args:
            record (dict): 弹幕历史记录行。
        """
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

    @Slot(str, object)
    def _on_video_fetch_failed(self, bvid: str, err: Exception):
        """
        B 站 API 视频详情获取失败 (超时或 404)

        将缓存置空，从拉取池中释放，并恢复表格默认显示。
        """
        if bvid in self._fetched_bvids:
            self._fetched_bvids.remove(bvid)
        self._model.update_video_cache(bvid, None)

    # endregion

    # region Slots HistoryController
    @Slot(int, object)
    def _on_history_query_succeeded(self, seq: int, records: list):
        """
        本地 SQLite 查询完成回调

        将结果刷入表格，并触发缺失元数据的后台补全；早于当前请求的结果丢弃。
        """
        if seq < self._query_seq:
            return
        self._model.set_records(records)
        self._fetch_missing_metadata(records)

    @Slot(int, object)
    def _on_history_failed(self, seq: int, err: Exception):
        """弹幕查询失败兜底；早于当前请求的失败丢弃，当前失败时空态换失败提示。

        通常因数据库锁定或文件损坏导致。
        """
        if seq < self._query_seq:
            return
        logger.error(f"历史记录数据库查询失败: {err!s}")
        self._bridge.set_empty("查询失败", "点击「刷新数据」重试", "刷新数据")

    @Slot(int, object)
    def _on_tasks_failed(self, seq: int, err: Exception):
        """任务清单加载失败兜底；早于当前请求的失败丢弃，当前失败时空态换失败提示。"""
        if seq < self._task_seq:
            return
        logger.error(f"任务清单加载失败: {err!s}")
        self._bridge.set_empty("查询失败", "点击「刷新数据」重试", "刷新数据")

    @Slot(object)
    def _on_verify_failed(self, err: Exception):
        """弹幕验证失败兜底；只记日志，不写表空态。"""
        logger.error(f"弹幕验证失败: {err!s}")

    # endregion

    def _verify_records(self, record: dict):
        """触发单个分P的弹幕验证"""
        if not self.state.session.sessdata:
            logger.warning("未登录，无法验证弹幕。")
            return
        cid = record['cid']
        logger.info(f"开始验证 CID {cid} 的弹幕状态...")
        self.history_controller.verify_records(cid)

    def _verify_all(self):
        """触发全部待验证弹幕的批量验证"""
        if not self.state.session.sessdata:
            logger.warning("未登录，无法验证弹幕。")
            return
        logger.info("开始批量验证所有待验证弹幕...")
        self.history_controller.verify_all()

    @Slot(dict)
    def _on_verify_completed(self, result: VerifyResult):
        """验证完成回调"""
        verified = result["verified"]
        lost = result['lost']
        logger.info(f"验证完成: 核销 {verified} 条，标记丢失 {lost} 条。")
        self._refresh_data()

    # region Slots QML 场景
    @Slot(int)
    def _on_record_picked(self, row: int) -> None:
        """挑定记录动作对象：双击与右键先经此快照，动作不随模型刷新漂移。"""
        self._picked_record = self._model.get_record_at(row)

    @Slot()
    def _open_record(self) -> None:
        """打开挑定记录的明细对话框。"""
        record = self._picked_record
        if record:
            self._show_detail_dialog(record)

    @Slot()
    def _open_in_browser(self) -> None:
        """在浏览器打开挑定记录对应分P。"""
        record = self._picked_record
        if not record:
            return
        url = f"https://www.bilibili.com/video/{record['bvid']}"
        video_info = self._model.get_video_info(record['bvid'])
        if video_info:
            part = video_info.get_part_by_cid(record['cid'])
            if part:
                url += f"?p={part.page}"
        QDesktopServices.openUrl(QUrl(url))

    @Slot()
    def _on_verify_part(self) -> None:
        """核销挑定记录分P的所有弹幕。"""
        record = self._picked_record
        if record:
            self._verify_records(record)

    @Slot()
    def _copy_bvid(self) -> None:
        """复制挑定记录的 BVID。"""
        record = self._picked_record
        if record:
            QApplication.clipboard().setText(record['bvid'])

    @Slot()
    def _copy_content(self) -> None:
        """复制挑定记录的弹幕内容。"""
        record = self._picked_record
        if record:
            QApplication.clipboard().setText(record['msg'])

    # endregion
    # endregion
