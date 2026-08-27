import logging

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QFileDialog, QMessageBox, QGroupBox
)
from PySide6.QtCore import Qt, Signal, Slot

from danmaku_sender.controller.video_controller import VideoController
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.video import VideoInfo
from danmaku_sender.types.models.queue import QueueTask, TaskStatus
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.config import ApiAuthConfig, SenderConfig
from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.service.danmaku_parser import DanmakuParser
from danmaku_sender.utils.string_utils import parse_bilibili_link



logger = logging.getLogger(__name__)


class TaskBuilderDialog(QDialog):
    """任务构建弹窗：选择视频 → 选择分P → 选择弹幕文件 → 添加到队列"""

    taskCreated = Signal(QueueTask)  # 每创建一个任务就发射

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.video_controller = VideoController(self)
        self._video_info: VideoInfo | None = None
        self._selected_files: list[str] = []
        self._pending_part_index: int | None = None

        self.setWindowTitle("添加任务到队列")
        self.setMinimumWidth(500)
        self._create_ui()
        self._connect_signals()

    def _create_ui(self):
        layout = QVBoxLayout(self)

        group = QGroupBox("新建任务")
        form = QFormLayout(group)
        form.setSpacing(10)

        # 目标视频
        bv_row = QHBoxLayout()
        self._bv_input = QLineEdit()
        self._bv_input.setPlaceholderText("输入BV号或视频链接")
        self._fetch_btn = QPushButton("获取视频信息")
        self._fetch_btn.setFixedWidth(100)
        bv_row.addWidget(self._bv_input)
        bv_row.addWidget(self._fetch_btn)
        form.addRow("目标视频:", bv_row)

        # 分P选择
        self._part_combo = QComboBox()
        self._part_combo.setPlaceholderText("请先获取视频信息")
        self._part_combo.setEnabled(False)
        form.addRow("分P选择:", self._part_combo)

        # 弹幕文件
        file_row = QHBoxLayout()
        self._file_input = QLineEdit()
        self._file_input.setPlaceholderText("未选择文件（可稍后添加）")
        self._file_input.setReadOnly(True)
        self._file_btn = QPushButton("选择文件")
        self._file_btn.setFixedWidth(80)
        file_row.addWidget(self._file_input, stretch=1)
        file_row.addWidget(self._file_btn)
        form.addRow("弹幕文件:", file_row)

        layout.addWidget(group)

        # --- 按钮 ---
        btn_layout = QHBoxLayout()
        self._btn_add = QPushButton("添加到队列")
        self._btn_add.setFixedWidth(100)
        self._btn_add.setEnabled(False)

        btn_layout.addStretch()
        btn_layout.addWidget(self._btn_add)

        layout.addLayout(btn_layout)

    def _connect_signals(self):
        self._fetch_btn.clicked.connect(self._fetch_video)
        self._file_btn.clicked.connect(self._select_files)
        self._btn_add.clicked.connect(self._add_task)
        self._part_combo.currentIndexChanged.connect(self._update_add_button)

        self.video_controller.fetchSucceeded.connect(self._on_fetch_succeeded)
        self.video_controller.fetchFailed.connect(self._on_fetch_failed)

    def _update_add_button(self):
        """根据状态决定添加按钮是否可用"""
        has_part = self._part_combo.currentIndex() >= 0 and self._part_combo.currentData() is not None
        self._btn_add.setEnabled(has_part)

    @Slot()
    def _fetch_video(self):
        raw = self._bv_input.text().strip()
        if not raw:
            return

        bvid, p_index = parse_bilibili_link(raw)
        if not bvid:
            QMessageBox.warning(self, "格式错误", "未能识别有效的 BV 号。")
            return

        self._bv_input.setText(bvid)
        self._pending_part_index = p_index
        self._fetch_btn.setEnabled(False)
        self._fetch_btn.setText("获取中...")
        self._part_combo.clear()
        self._part_combo.setEnabled(False)

        self.video_controller.fetch_single_info(bvid, self.state.get_api_auth())

    @Slot(str, VideoInfo)
    def _on_fetch_succeeded(self, bvid: str, info: VideoInfo):
        self._video_info = info
        self._fetch_btn.setEnabled(True)
        self._fetch_btn.setText("获取视频信息")
        self._part_combo.setEnabled(True)

        self._part_combo.clear()
        for p in info.parts:
            if p.cid:
                self._part_combo.addItem(f"P{p.page} - {p.title}", userData={'cid': p.cid, 'page': p.page})

        if self._part_combo.count() > 0:
            if self._pending_part_index is not None and 0 <= self._pending_part_index < self._part_combo.count():
                self._part_combo.setCurrentIndex(self._pending_part_index)
            else:
                self._part_combo.setCurrentIndex(0)
            self._pending_part_index = None

        self._update_add_button()

    @Slot(str, str)
    def _on_fetch_failed(self, bvid: str, error_msg: str):
        self._fetch_btn.setEnabled(True)
        self._fetch_btn.setText("获取视频信息")
        QMessageBox.warning(self, "获取失败", f"无法获取视频信息:\n{error_msg}")

    @Slot()
    def _select_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择弹幕XML文件", "", "XML Files (*.xml)"
        )
        if files:
            self._selected_files = files
            if len(files) == 1:
                self._file_input.setText(files[0].split("/")[-1].split("\\")[-1])
            else:
                self._file_input.setText(f"已选择 {len(files)} 个文件")
        else:
            self._selected_files = []
            self._file_input.clear()

    @Slot()
    def _add_task(self):
        if not self._video_info:
            return

        data = self._part_combo.currentData()
        if not data:
            return

        cid = data['cid']
        page = data['page']
        part_title = ""
        if self._video_info:
            for p in self._video_info.parts:
                if p.cid == cid:
                    part_title = p.title
                    break

        target = VideoTarget(
            bvid=self._video_info.bvid,
            cid=cid,
            title=self._video_info.title,
        )

        # 获取视频时长（毫秒）
        duration_ms = 0
        for p in self._video_info.parts:
            if p.cid == cid:
                duration_ms = p.duration * 1000  # 秒转毫秒
                break

        # 解析弹幕文件（如果选了的话）
        danmakus = []
        xml_path = ""
        if self._selected_files:
            parser = DanmakuParser()
            file_idx = min(self._part_combo.currentIndex(), len(self._selected_files) - 1)
            xml_path = self._selected_files[file_idx]
            try:
                danmakus = parser.parse_xml_file(xml_path)
            except Exception as e:
                QMessageBox.warning(self, "解析失败", f"弹幕文件解析失败:\n{e}")
                return

        task = QueueTask(
            target=target,
            danmakus=danmakus,
            config_snapshot=self.state.sender_config.model_copy(),
            p_index=page,
            p_title=part_title,
            xml_path=xml_path,
            duration_ms=duration_ms,
        )

        # 如果没有弹幕，标记为未配置
        if not danmakus:
            danmakus.append(Danmaku(msg="未选择弹幕文件-示例弹幕", progress=0, mode=Danmaku.Mode.SCROLL))
            task.total = len(task.danmakus)
            task.status = TaskStatus.UNCONFIGURED

        self.taskCreated.emit(task)
        logger.info(f"任务已创建: {target.display_string} ({len(danmakus)} 条弹幕, {task.status.value})")

        # 添加后保留分P选择，只清空文件选择
        self._selected_files = []
        self._file_input.clear()
