import logging
from typing import Callable

from PySide6.QtCore import QObject, Signal

from danmaku_sender.ui.framework.concurrency import PoolTask
from danmaku_sender.core.engines.editor_session import EditorSession
from danmaku_sender.runtime.app_state import AppState
from danmaku_sender.core.models.danmaku import Danmaku
from danmaku_sender.core.models.editor_types import ViewItem, InsertPosition
from danmaku_sender.core.services.danmaku_parser import DanmakuParser
from danmaku_sender.core.services.danmaku_exporter import export_danmakus_to_xml


class EditorController(QObject):
    """
    编辑器业务控制器 (Mediator / ViewModel)

    负责桥接 UI、AppState 与 EditorSession。
    """
    dataChanged = Signal()

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger("App.System.Editor.Controller")
        self.state = state
        self.session = EditorSession()

    # region Computed Properties for UI

    @property
    def has_data(self) -> bool:
        """工作区是否有数据"""
        return self.session.has_active_session

    @property
    def source_data_exists(self) -> bool:
        """全局状态中是否有待加载的源数据"""
        return bool(self.state.video_state.loaded_danmakus)

    @property
    def has_video_context(self) -> bool:
        """是否拥有关联的视频上下文（BVID/CID）"""
        return bool(self.state.video_state.selected_cid)

    @property
    def is_dirty(self) -> bool:
        """是否有未保存的修改"""
        return self.session.is_dirty

    @property
    def can_undo(self) -> bool:
        """是否可以撤销"""
        return self.session.can_undo

    @property
    def active_error_count(self) -> int:
        """当前报错的弹幕数量"""
        return self.session.active_error_count

    # endregion
    # region Workflow Actions

    def create_new_workspace(self):
        """新建空白工作区并清除视频上下文"""
        self.state.video_state.loaded_danmakus =[
            Danmaku(msg="在这里输入你的第一条弹幕吧", progress=0)
        ]
        self.state.video_state.bvid = ""
        self.state.video_state.selected_cid = None
        self.state.video_state.video_title = ""

        self.load_from_state()

    def import_xml_to_workspace(self, file_path: str, on_success: Callable[[int], None], on_error: Callable[[str], None]):
        """
        异步导入 XML 文件到工作区：解析在后台线程执行，状态更新在 UI 线程回调。

        注意: on_success / on_error 回调由 Qt 信号机制保证在主线程执行，
        因此回调内可安全操作 UI 状态。

        Args:
            file_path: XML 文件路径
            on_success: 成功回调，接收解析数量
            on_error: 失败回调，接收错误信息
        """
        parser = DanmakuParser()
        PoolTask.submit(
            parser.parse_xml_file,
            lambda parsed: on_success(self._apply_parsed_to_workspace(parsed)),
            lambda err: on_error(str(err)),
            file_path,
        )

    def export_to_xml(
        self,
        danmakus: list[Danmaku],
        file_path: str,
        on_success: Callable[[None], None],
        on_error: Callable[[str], None],
    ):
        """异步导出弹幕列表到 XML 文件"""
        PoolTask.submit(
            export_danmakus_to_xml,
            on_success,
            lambda err: on_error(str(err)),
            danmakus, file_path,
        )

    def _apply_parsed_to_workspace(self, parsed_dms: list[Danmaku] | None) -> int:
        """
        将已解析的弹幕列表写入工作区，清除视频上下文，拉入编辑器沙盒。

        Returns:
            int: 成功解析的弹幕数量
        """
        if not parsed_dms:
            return 0

        self.state.video_state.loaded_danmakus = parsed_dms
        self.state.video_state.bvid = ""
        self.state.video_state.selected_cid = None
        self.state.video_state.video_title = ""

        self.load_from_state()
        return len(parsed_dms)

    def load_from_state(self) -> bool:
        """从 AppState 检出数据到沙盒，并执行初次校验"""
        source = self.state.video_state.loaded_danmakus
        if not source:
            return False

        self.session.load_data(source)
        self.run_validation()
        self.session.mark_head_errors()  # 锁定初始错误快照
        self.session.set_dirty(False)
        self.dataChanged.emit()
        return self.active_error_count > 0

    def commit_to_state(self) -> tuple[int, int, int]:
        """将修改结果提交回 AppState，清空沙盒"""
        final_list, fixed, removed = self.session.get_committed_data()
        self.state.video_state.loaded_danmakus = final_list

        # 提交后重置沙盒
        self.session.load_data([])
        self.dataChanged.emit()
        return len(final_list), fixed, removed

    def get_working_danmakus(self) -> list[Danmaku]:
        """提取当前工作区中所有未删除的弹幕 (供导出 XML 用)"""
        if not self.session.has_active_session:
            return []
        return [
            self.session.items[uid].working
            for uid in self.session.item_order
            if not self.session.items[uid].is_deleted
        ]

    def run_validation(self):
        """执行校验：自动向沙盒注入最新的校验参数"""
        duration = -1
        if self.has_video_context:
            duration = self.state.video_state.selected_part_duration_ms

        config = self.state.validation_config
        self.session.validate(duration_ms=duration, config=config)
        self.dataChanged.emit()

    # endregion
    # region Atomic Operation Routing

    def insert_item(self, ref_uid: str, pos: InsertPosition) -> str | None:
        uid = self.session.insert_item(ref_uid, pos)
        if uid:
            self.run_validation()
        return uid

    def update_properties(self, uid: str, props: dict) -> bool:
        if self.session.update_item_properties(uid, props):
            self.run_validation()
            return True
        return False

    def delete_items(self, uids: list[str]):
        if self.session.delete_items(uids):
            self.run_validation()

    def undo(self):
        if self.session.undo():
            self.run_validation()

    def batch_remove_newlines(self) -> tuple[int, int]:
        mod, dele = self.session.batch_remove_newlines()
        if mod > 0 or dele > 0:
            self.run_validation()
        return mod, dele

    def batch_truncate(self) -> int:
        count = self.session.batch_truncate_length()
        if count > 0:
            self.run_validation()
        return count

    def shift_time(self, offset_ms: int, target_uids: list[str] | None = None) -> int:
        count = self.session.shift_time_axis(offset_ms, target_uids)
        if count > 0:
            self.run_validation()
        return count

    def generate_array(self, ref_uid: str, text: str, mode: Danmaku.Mode, count: int, color_strategy: str) -> list[str]:
        new_uids = self.session.generate_danmaku_array(
            ref_uid, text, mode, count, color_strategy
        )
        if new_uids:
            self.run_validation()
        return new_uids

    # endregion
    # region View Data Extraction

    def get_view_model(self, show_all: bool = False) -> list[ViewItem]:
        return self.session.generate_view_model(show_all)

    def get_item_danmaku(self, uid: str) -> Danmaku | None:
        item = self.session.items.get(uid)
        return item.working if item else None

    # endregion