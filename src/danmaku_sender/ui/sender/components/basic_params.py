from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QComboBox,
    QLabel, QGroupBox, QCheckBox, QTableView
)
from PySide6.QtCore import QAbstractTableModel

from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.ui.framework.binder import UIBinder
from danmaku_sender.types.models.video import DestVideo

class VideoQueueTable(QAbstractTableModel):
    HEADERS = ["视频BV号", "分P", "弹幕文件", "状态"]
    def __init__(self, parent = None):
        super().__init__(parent)
        self._view_items = []

    def refresh_video_state(self, bv: str = None) -> None:
        for i, video in enumerate(self._view_items):
            if video.video.bvid == bv:
                video.video_state = "已获取"
                break
        self.dataChanged()


class BasicParamsGroup(QGroupBox):
    """基础参数区"""
    def __init__(self, state: AppState, parent=None):
        super().__init__("基础参数", parent)
        self.state = state
        self._create_ui()

    def _create_ui(self):
        layout = QFormLayout(self)

        # BV号
        bv_layout = QHBoxLayout()
        self.bv_input = QLineEdit()
        self.bv_input.setPlaceholderText("请输入视频BV号")
        self.fetch_btn = QPushButton("获取分P")
        bv_layout.addWidget(self.bv_input)
        bv_layout.addWidget(self.fetch_btn)

        # 分P选择
        self.part_combo = QComboBox()
        self.part_combo.setPlaceholderText("请选择分P")
        self.part_combo.setEnabled(False)

        # 弹幕文件选择
        file_layout = QHBoxLayout()
        self.file_input = QLineEdit()
        self.file_input.setReadOnly(True)
        self.file_input.setPlaceholderText("请选择弹幕 XML 文件")
        self.file_btn = QPushButton("选择文件")
        file_layout.addWidget(self.file_input)
        file_layout.addWidget(self.file_btn)

        # 视频队列
        video_queue_layout = QVBoxLayout()
        self.video_queue_table_view = QTableView()
        self.video_queue_model = VideoQueueTable()
        self.add_to_queue_btn = QPushButton("将当前视频及配置的弹幕文件添加到队列")
        self.video_queue_table_view.setModel(self.video_queue_model)
        video_queue_layout.addWidget(self.video_queue_table_view)
        video_queue_layout.addWidget(self.add_to_queue_btn)

        # 断点续传
        self.skip_sent_cb = QCheckBox("启用断点续传 (跳过已发送)")
        self.skip_sent_cb.setToolTip(
            "开启后，发送前会自动检查数据库。\n"
            "如果发现完全一致的弹幕（内容、时间、样式）已发送过，则自动跳过。"
        )

        layout.addRow(QLabel("视频BV号:"), bv_layout)
        layout.addRow(QLabel("分P选择:"), self.part_combo)
        layout.addRow(QLabel("弹幕文件:"), file_layout)
        layout.addRow(QLabel("视频队列:"), video_queue_layout)
        layout.addRow(QLabel(""), self.skip_sent_cb)

    def init_bindings(self):
        """将 UI 控件与 AppState 进行双向绑定"""
        UIBinder.bind(self.bv_input, self.state.video_queue.active_video, "bvid", realtime=True)
        UIBinder.bind(self.skip_sent_cb, self.state.sender_config, "skip_sent")
        # TODO 修改业务逻辑 添加视频到队列后再发射
        # 1. 绑定添加到队列的按钮
        # 2. 按下发射按钮后 检查队列中视频是否有效
        # 3. 修改发射逻辑，即顺序发射视频

        if self.state.video_queue.active_video.selected_part_name:
            self.part_combo.setPlaceholderText(self.state.video_queue.active_video.selected_part_name)

    def set_inputs_locked(self, locked: bool):
        """供主控调用的防误触锁"""
        enabled = not locked

        self.fetch_btn.setEnabled(enabled)
        self.file_btn.setEnabled(enabled)
        self.part_combo.setEnabled(enabled)
        self.bv_input.setReadOnly(locked)
        self.skip_sent_cb.setEnabled(enabled)
