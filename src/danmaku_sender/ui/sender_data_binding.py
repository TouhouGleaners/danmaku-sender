import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox

from danmaku_sender.controller.video_controller import VideoController
from danmaku_sender.controller.sender_controller import SenderController
from danmaku_sender.types.models.video import VideoInfo
from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.utils.string_utils import parse_bilibili_link


logger = logging.getLogger("App.Sender.DataBinding")


class SenderDataBinding(QObject):
    """发射器数据绑定层。

    负责文件加载、视频信息获取、分P选择等数据流操作。
    通过信号通知 UI 更新，不直接操作控件。
    """
    # 文件相关
    fileLoaded = Signal(str, int)       # filename, count
    fileLoadFailed = Signal(str, str)   # filename, error_msg

    # 视频相关
    videoFetchStarted = Signal()
    videoFetched = Signal(str, object)  # bvid, VideoInfo
    videoFetchFailed = Signal(str, str) # bvid, error_msg

    # 分P选择
    partSelected = Signal(int, int, str) # cid, duration_ms, part_name

    def __init__(self, state: AppState, sender_controller: SenderController,
                 video_controller: VideoController, parent=None):
        super().__init__(parent)
        self.state = state
        self.sender_controller = sender_controller
        self.video_controller = video_controller
        self._pending_part_index: int | None = None

        # 连接控制器信号
        self.sender_controller.xmlParsed.connect(self._on_xml_parsed)
        self.sender_controller.xmlParseFailed.connect(self._on_xml_parse_failed)
        self.video_controller.fetchStarted.connect(self._on_fetch_started)
        self.video_controller.fetchSucceeded.connect(self._on_fetch_succeeded)
        self.video_controller.fetchFailed.connect(self._on_fetch_failed)

        # 监听编辑器数据同步
        self.state.video_state.subscribe("loaded_danmakus", self._on_loaded_danmakus_changed)

    def select_file(self):
        """打开文件选择对话框"""
        file_path, _ = QFileDialog.getOpenFileName(None, "选择弹幕XML文件", "", "XML Files (*.xml);;All Files (*.*)")
        if file_path:
            self.load_file(file_path)

    def load_file(self, file_path: str):
        """加载 XML 文件"""
        logger.info(f"📥 正在解析文件: {Path(file_path).name}")
        self.sender_controller.load_xml_file(file_path)

    def fetch_video_info(self, raw_input: str):
        """解析 BV 号并获取视频信息"""
        if not raw_input:
            return

        bvid, p_index = parse_bilibili_link(raw_input)
        if not bvid:
            return

        self._pending_part_index = p_index
        self.video_controller.fetch_single_info(bvid, self.state.get_api_auth())

    def select_part(self, index: int, combo_data: dict | None, part_name: str):
        """处理分P选择"""
        if index < 0 or not combo_data or not isinstance(combo_data, dict):
            return

        cid = combo_data['cid']
        duration = combo_data['duration']

        self.state.video_state.selected_cid = cid
        self.state.video_state.selected_part_duration_ms = duration * 1000
        self.state.video_state.selected_part_name = part_name
        logger.info(f"已选择分P: {part_name} (CID: {cid})")

    @property
    def pending_part_index(self) -> int | None:
        return self._pending_part_index

    def clear_pending_part_index(self):
        self._pending_part_index = None

    # region Controller Callbacks

    @Slot(str, int)
    def _on_xml_parsed(self, file_path: str, count: int):
        self.fileLoaded.emit(Path(file_path).name, count)

    @Slot(str, object)
    def _on_xml_parse_failed(self, file_path: str, err: Exception):
        self.fileLoadFailed.emit(str(err), "")

    @Slot()
    def _on_fetch_started(self):
        self.videoFetchStarted.emit()

    @Slot(str, VideoInfo)
    def _on_fetch_succeeded(self, bvid: str, info: VideoInfo):
        self.state.video_state.video_title = info.title
        self.state.video_state.cid_parts_map = {}
        logger.info(f"获取成功: {info.title}, 共 {len(info.parts)} 个分P")
        self.videoFetched.emit(bvid, info)

    @Slot(str, object)
    def _on_fetch_failed(self, bvid: str, err: Exception):
        self._pending_part_index = None
        logger.error(f"获取视频信息失败: {str(err)}")
        self.videoFetchFailed.emit(bvid, str(err))

    def _on_loaded_danmakus_changed(self, _value):
        """编辑器提交弹幕后通知 UI"""
        pass  # UI 层通过信号自行处理

    # endregion
