import logging

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QCheckBox, QSpinBox, QDoubleSpinBox, QPushButton, QGroupBox,
    QTextEdit, QTabWidget, QWidget, QLineEdit, QComboBox, QFileDialog
)
from PySide6.QtCore import Qt, Signal, Slot

from danmaku_sender.types.models.queue import QueueTask, TaskStatus
from danmaku_sender.types.models.video import VideoInfo
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.config import SenderConfig
from danmaku_sender.controller.video_controller import VideoController
from danmaku_sender.service.danmaku_parser import DanmakuParser
from danmaku_sender.utils.string_utils import parse_bilibili_link


logger = logging.getLogger(__name__)


class TaskDetailDialog(QDialog):
    """任务详情与配置编辑弹窗"""

    def __init__(self, task: QueueTask, api_auth, parent=None):
        super().__init__(parent)
        self.task = task
        self._api_auth = api_auth
        self._video_info: VideoInfo | None = None
        self._pending_part_index: int | None = None
        self._selected_file: str | None = None
        self._video_controller = VideoController(self)

        self.setWindowTitle(f"编辑任务 — {task.target.display_string}")
        self.setMinimumSize(500, 500)
        self._create_ui()
        self._connect_signals()
        self._load_task_info()

    def _create_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()

        # --- 任务信息 Tab ---
        info_tab = QWidget()
        info_layout = QVBoxLayout(info_tab)
        info_layout.addWidget(self._create_info_section())
        tabs.addTab(info_tab, "任务信息")

        # --- 配置 Tab ---
        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)
        config_layout.addWidget(self._create_config_section())
        tabs.addTab(config_tab, "发送配置")

        layout.addWidget(tabs)

        # --- 按钮 ---
        btn_layout = QHBoxLayout()
        self._btn_save = QPushButton("保存")
        self._btn_close = QPushButton("关闭")

        self._btn_save.clicked.connect(self._on_save)
        self._btn_close.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self._btn_close)
        btn_layout.addWidget(self._btn_save)

        layout.addLayout(btn_layout)

    def _create_info_section(self) -> QWidget:
        group = QGroupBox("任务信息")
        layout = QVBoxLayout(group)

        # --- 可编辑区：视频目标 ---
        edit_group = QGroupBox("视频目标")
        edit_form = QFormLayout(edit_group)

        bv_row = QHBoxLayout()
        self._bv_input = QLineEdit()
        self._bv_input.setPlaceholderText("输入BV号或视频链接")
        self._bv_input.setText(self.task.target.bvid)
        self._fetch_btn = QPushButton("获取视频信息")
        self._fetch_btn.setFixedWidth(100)
        bv_row.addWidget(self._bv_input)
        bv_row.addWidget(self._fetch_btn)
        edit_form.addRow("BVID:", bv_row)

        self._part_combo = QComboBox()
        self._part_combo.setEnabled(False)
        edit_form.addRow("分P选择:", self._part_combo)

        file_row = QHBoxLayout()
        self._file_input = QLineEdit()
        self._file_input.setReadOnly(True)
        if self.task.xml_path:
            self._file_input.setText(self.task.xml_path)
        elif self.task.danmakus:
            self._file_input.setText(f"已加载 {len(self.task.danmakus)} 条弹幕")
        self._file_btn = QPushButton("选择文件")
        self._file_btn.setFixedWidth(80)
        file_row.addWidget(self._file_input, stretch=1)
        file_row.addWidget(self._file_btn)
        edit_form.addRow("弹幕文件:", file_row)

        layout.addWidget(edit_group)

        # --- 只读区：任务详情 ---
        detail_group = QGroupBox("当前信息")
        detail_form = QFormLayout(detail_group)

        task = self.task
        url = f"https://www.bilibili.com/video/{task.target.bvid}"
        if task.p_index > 0:
            url += f"?p={task.p_index}"

        detail_form.addRow("任务ID:", QLabel(task.task_id))
        self._detail_title = QLabel(task.target.title or task.target.bvid)
        self._detail_bvid = QLabel(task.target.bvid)
        self._detail_part = QLabel(f"P{task.p_index} - {task.p_title}" if task.p_title else f"P{task.p_index}")
        self._detail_cid = QLabel(str(task.target.cid))
        self._detail_url = QLabel(url)
        detail_form.addRow("视频:", self._detail_title)
        detail_form.addRow("BVID:", self._detail_bvid)
        detail_form.addRow("分P:", self._detail_part)
        detail_form.addRow("CID:", self._detail_cid)
        detail_form.addRow("链接:", self._detail_url)
        detail_form.addRow("状态:", QLabel(task.status.value))
        detail_form.addRow("进度:", QLabel(f"{task.attempted}/{task.total}"))
        self._detail_dm_count = QLabel(str(len(task.danmakus)))
        detail_form.addRow("弹幕数:", self._detail_dm_count)
        if task.error_msg:
            detail_form.addRow("错误:", QLabel(task.error_msg))

        layout.addWidget(detail_group)

        return group

    def _connect_signals(self):
        self._fetch_btn.clicked.connect(self._fetch_video)
        self._file_btn.clicked.connect(self._select_file)
        self._video_controller.fetchSucceeded.connect(self._on_fetch_succeeded)
        self._video_controller.fetchFailed.connect(self._on_fetch_failed)
        self._part_combo.currentIndexChanged.connect(self._on_part_changed)

    def _load_task_info(self):
        """预填当前任务的分P信息"""
        task = self.task
        if task.p_index > 0:
            label = f"P{task.p_index} - {task.p_title}" if task.p_title else f"P{task.p_index}"
            self._part_combo.addItem(label, userData={'cid': task.target.cid, 'page': task.p_index})
            self._part_combo.setCurrentIndex(0)

    @Slot()
    def _fetch_video(self):
        raw = self._bv_input.text().strip()
        if not raw:
            return
        bvid, p_index = parse_bilibili_link(raw)
        if not bvid:
            return
        self._bv_input.setText(bvid)
        self._pending_part_index = None
        # 只有 BV 号变化且链接带 ?p= 时才用 p_index 定位
        if bvid != self.task.target.bvid and p_index is not None:
            self._pending_part_index = p_index
        self._fetch_btn.setEnabled(False)
        self._fetch_btn.setText("获取中...")
        self._part_combo.clear()
        self._part_combo.setEnabled(False)
        self._video_controller.fetch_single_info(bvid, self._api_auth)

    @Slot(str, VideoInfo)
    def _on_fetch_succeeded(self, bvid: str, info: VideoInfo):
        self._video_info = info
        self._fetch_btn.setEnabled(True)
        self._fetch_btn.setText("获取视频信息")
        self._part_combo.setEnabled(True)

        self._part_combo.currentIndexChanged.disconnect(self._on_part_changed)
        self._part_combo.clear()
        for p in info.parts:
            if p.cid:
                self._part_combo.addItem(f"P{p.page} - {p.title}", userData={'cid': p.cid, 'page': p.page})
        self._part_combo.currentIndexChanged.connect(self._on_part_changed)

        if self._part_combo.count() > 0:
            if self._pending_part_index is not None and 0 <= self._pending_part_index < self._part_combo.count():
                self._part_combo.setCurrentIndex(self._pending_part_index)
            else:
                # 默认选中当前任务的分P
                for i in range(self._part_combo.count()):
                    data = self._part_combo.itemData(i)
                    if data and data['cid'] == self.task.target.cid:
                        self._part_combo.setCurrentIndex(i)
                        break
                else:
                    self._part_combo.setCurrentIndex(0)
            self._pending_part_index = None

    @Slot(str, str)
    def _on_fetch_failed(self, bvid: str, error_msg: str):
        self._fetch_btn.setEnabled(True)
        self._fetch_btn.setText("获取视频信息")

    @Slot()
    def _select_file(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择弹幕XML文件", "", "XML Files (*.xml)")
        if files:
            self._selected_file = files[0]
            self._file_input.setText(files[0].split("/")[-1].split("\\")[-1])
            # 预览弹幕数量
            parser = DanmakuParser()
            try:
                danmakus = parser.parse_xml_file(files[0])
                self._detail_dm_count.setText(f"{len(danmakus)} (待保存)")
            except Exception:
                self._detail_dm_count.setText("解析失败")

    @Slot(int)
    def _on_part_changed(self, index: int):
        data = self._part_combo.itemData(index)
        if not data:
            return
        if self._video_info:
            self._pending_part_index = data.get('page')
        # 刷新底部详情
        self._update_detail_display(data)

    def _update_detail_display(self, data: dict):
        """根据选中的分P刷新底部信息"""
        cid = data['cid']
        page = data['page']
        title = self._video_info.title if self._video_info else self.task.target.title
        bvid = self._video_info.bvid if self._video_info else self.task.target.bvid
        part_text = self._part_combo.currentText()

        self._detail_title.setText(title or bvid)
        self._detail_bvid.setText(bvid)
        self._detail_part.setText(part_text)
        self._detail_cid.setText(str(cid))
        url = f"https://www.bilibili.com/video/{bvid}?p={page}"
        self._detail_url.setText(url)

    def _on_save(self):
        """保存编辑结果"""
        task = self.task

        # 更新视频目标（如果有新选择）
        data = self._part_combo.currentData()
        if data and self._video_info:
            task.target = VideoTarget(
                bvid=self._video_info.bvid,
                cid=data['cid'],
                title=self._video_info.title,
            )
            task.p_index = data['page']
            # 从 combo 文本中提取分P标题
            combo_text = self._part_combo.currentText()
            if " - " in combo_text:
                task.p_title = combo_text.split(" - ", 1)[1]
            else:
                task.p_title = ""

        # 更新弹幕文件（如果有新选择）
        if self._selected_file:
            parser = DanmakuParser()
            try:
                danmakus = parser.parse_xml_file(self._selected_file)
                if danmakus:
                    task.danmakus = danmakus
                    task.total = len(danmakus)
                    task.xml_path = self._selected_file
                    if task.status == TaskStatus.UNCONFIGURED:
                        task.status = TaskStatus.PENDING
            except Exception as e:
                logger.error(f"弹幕文件解析失败: {e}")

        self.accept()

    def get_config(self) -> SenderConfig:
        """返回编辑后的配置"""
        return SenderConfig(
            min_delay=self._min_delay.value(),
            max_delay=self._max_delay.value(),
            burst_enabled=self._burst_cb.isChecked(),
            burst_size=self._burst_size.value(),
            rest_min=self._rest_min.value(),
            rest_max=self._rest_max.value(),
            stop_after_count=self._stop_count.value(),
            stop_after_time=self._stop_time.value(),
            delay_between_tasks=self._delay_between.value(),
            prevent_sleep=self.task.config_snapshot.prevent_sleep,
            use_system_proxy=self.task.config_snapshot.use_system_proxy,
            skip_sent=self.task.config_snapshot.skip_sent,
        )

    # --- 配置编辑 ---

    def _create_config_section(self) -> QWidget:
        group = QGroupBox("发送配置")
        layout = QVBoxLayout(group)

        # --- 发送延迟 ---
        delay_group = QGroupBox("发送延迟")
        delay_form = QFormLayout(delay_group)

        delay_row = QHBoxLayout()
        delay_row.setSpacing(2)
        self._min_delay = QDoubleSpinBox()
        self._min_delay.setRange(0.1, 60.0)
        self._min_delay.setSingleStep(0.5)
        self._min_delay.setFixedWidth(70)
        delay_row.addWidget(self._min_delay)
        delay_row.addWidget(QLabel("-"))
        self._max_delay = QDoubleSpinBox()
        self._max_delay.setRange(0.1, 60.0)
        self._max_delay.setSingleStep(0.5)
        self._max_delay.setFixedWidth(70)
        delay_row.addWidget(self._max_delay)
        delay_row.addWidget(QLabel("秒"))
        delay_row.addStretch()
        delay_form.addRow("随机间隔:", delay_row)

        burst_row = QHBoxLayout()
        burst_row.setSpacing(2)
        self._burst_cb = QCheckBox("爆发模式")
        self._burst_cb.toggled.connect(self._on_burst_toggled)
        burst_row.addWidget(self._burst_cb)
        burst_row.addWidget(QLabel("每"))
        self._burst_size = QSpinBox()
        self._burst_size.setRange(2, 100)
        self._burst_size.setFixedWidth(70)
        burst_row.addWidget(self._burst_size)
        burst_row.addWidget(QLabel("条，休息"))
        self._rest_min = QDoubleSpinBox()
        self._rest_min.setRange(0.0, 300.0)
        self._rest_min.setFixedWidth(60)
        burst_row.addWidget(self._rest_min)
        burst_row.addWidget(QLabel("-"))
        self._rest_max = QDoubleSpinBox()
        self._rest_max.setRange(0.0, 300.0)
        self._rest_max.setFixedWidth(60)
        burst_row.addWidget(self._rest_max)
        burst_row.addWidget(QLabel("秒"))
        burst_row.addStretch()
        delay_form.addRow(burst_row)

        self._burst_controls: list[QWidget] = [self._burst_size, self._rest_min, self._rest_max]
        layout.addWidget(delay_group)

        # --- 自动终止 ---
        stop_group = QGroupBox("自动终止")
        stop_form = QFormLayout(stop_group)

        stop_count_row = QHBoxLayout()
        stop_count_row.setSpacing(2)
        self._stop_count = QSpinBox()
        self._stop_count.setRange(0, 99999)
        self._stop_count.setFixedWidth(70)
        stop_count_row.addWidget(self._stop_count)
        stop_count_row.addWidget(QLabel("条"))
        stop_count_row.addWidget(QLabel("(0为不限制)"))
        stop_count_row.addStretch()
        stop_form.addRow("已发送 >=", stop_count_row)

        stop_time_row = QHBoxLayout()
        stop_time_row.setSpacing(2)
        self._stop_time = QSpinBox()
        self._stop_time.setRange(0, 99999)
        self._stop_time.setFixedWidth(70)
        stop_time_row.addWidget(self._stop_time)
        stop_time_row.addWidget(QLabel("分钟"))
        stop_time_row.addWidget(QLabel("(0为不限制)"))
        stop_time_row.addStretch()
        stop_form.addRow("已用时 >=", stop_time_row)

        layout.addWidget(stop_group)

        # --- 队列设置 ---
        queue_group = QGroupBox("队列设置")
        queue_form = QFormLayout(queue_group)

        self._delay_between = QDoubleSpinBox()
        self._delay_between.setRange(0.0, 300.0)
        self._delay_between.setSingleStep(5.0)
        queue_form.addRow("任务间隔:", self._delay_between)

        layout.addWidget(queue_group)

        self._load_config_values()

        return group

    def _load_config_values(self):
        cfg = self.task.config_snapshot
        self._min_delay.setValue(cfg.min_delay)
        self._max_delay.setValue(cfg.max_delay)
        self._burst_cb.setChecked(cfg.burst_enabled)
        self._burst_size.setValue(cfg.burst_size)
        self._rest_min.setValue(cfg.rest_min)
        self._rest_max.setValue(cfg.rest_max)
        self._stop_count.setValue(cfg.stop_after_count)
        self._stop_time.setValue(cfg.stop_after_time)
        self._delay_between.setValue(cfg.delay_between_tasks)
        self._on_burst_toggled(cfg.burst_enabled)

    def _on_burst_toggled(self, checked: bool):
        for ctrl in self._burst_controls:
            ctrl.setEnabled(checked)
