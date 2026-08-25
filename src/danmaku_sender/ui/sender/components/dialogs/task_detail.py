import logging
from copy import deepcopy

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QCheckBox, QSpinBox, QDoubleSpinBox, QPushButton, QGroupBox,
    QTextEdit, QTabWidget, QWidget, QLineEdit, QComboBox, QFileDialog,
    QMessageBox
)
from PySide6.QtCore import Qt, Signal, Slot

from danmaku_sender.types.models.queue import QueueTask, TaskStatus
from danmaku_sender.types.models.video import VideoInfo
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.config import SenderConfig
from danmaku_sender.controller.video_controller import VideoController
from danmaku_sender.service.danmaku_parser import DanmakuParser
from danmaku_sender.utils.string_utils import parse_bilibili_link
from danmaku_sender.ui.framework.binder import UIBinder


logger = logging.getLogger(__name__)


class TaskDetailDialog(QDialog):
    """任务详情与配置编辑弹窗

    编辑沙盒模式:
    - origin: 原始任务（只读引用，保存时才写入）
    - editing: 编辑副本（所有修改在这里进行）
    - 配置区通过 UIBinder 绑定到 editing.config_snapshot，实时验证 + 自动变红
    - 取消时丢弃 editing，不做任何修改
    """

    def __init__(self, task: QueueTask, api_auth, queue_active: bool = False, parent=None):
        super().__init__(parent)
        self.origin = task                  # 原始引用（只读）
        self.editing = deepcopy(task)       # 编辑副本（工作区）
        self._api_auth = api_auth
        self._video_info: VideoInfo | None = None
        self._pending_part_index: int | None = None
        self._selected_file: str | None = None
        self._video_controller = VideoController(self)
        self._is_editable = (
            not queue_active
            and task.status in (TaskStatus.PENDING, TaskStatus.UNCONFIGURED)
        )

        self.setWindowTitle(f"编辑任务 — {task.target.display_string}")
        self.setMinimumSize(500, 500)
        self._create_ui()
        self._connect_signals()
        self._load_task_info()

        # 非可编辑状态时禁用所有编辑控件
        if not self._is_editable:
            self._set_readonly_mode()

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
        self._bv_input.setText(self.origin.target.bvid)
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
        if self.origin.xml_path:
            self._file_input.setText(self.origin.xml_path)
        elif self.origin.danmakus:
            self._file_input.setText(f"已加载 {len(self.origin.danmakus)} 条弹幕")
        self._file_btn = QPushButton("选择文件")
        self._file_btn.setFixedWidth(80)
        file_row.addWidget(self._file_input, stretch=1)
        file_row.addWidget(self._file_btn)
        edit_form.addRow("弹幕文件:", file_row)

        layout.addWidget(edit_group)

        # --- 只读区：任务详情 ---
        detail_group = QGroupBox("当前信息")
        detail_form = QFormLayout(detail_group)

        task = self.origin
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
        task = self.origin
        if task.p_index > 0:
            label = f"P{task.p_index} - {task.p_title}" if task.p_title else f"P{task.p_index}"
            self._part_combo.addItem(label, userData=task.p_index)
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
        # 只要链接带 ?p= 就用 p_index 定位（不论 BVID 是否变化）
        if p_index is not None:
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

        self._populate_part_combo(info)
        self._select_default_part()

    def _populate_part_combo(self, info: VideoInfo):
        """用视频信息填充分P下拉框"""
        self._part_combo.currentIndexChanged.disconnect(self._on_part_changed)
        self._part_combo.clear()
        for p in info.parts:
            if p.cid:
                self._part_combo.addItem(f"P{p.page} - {p.title}", userData=p.page)
        self._part_combo.currentIndexChanged.connect(self._on_part_changed)

    def _select_default_part(self):
        """选择默认的分P（优先用 pending，否则匹配当前任务）"""
        if self._part_combo.count() == 0:
            return

        if self._pending_part_index is not None and 0 <= self._pending_part_index < self._part_combo.count():
            self._part_combo.setCurrentIndex(self._pending_part_index)
        else:
            target_index = next(
                (i for i in range(self._part_combo.count())
                 if self._part_combo.itemData(i) == self.origin.p_index),
                0
            )
            self._part_combo.setCurrentIndex(target_index)

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
        page = self._part_combo.itemData(index)
        if page is None:
            return
        if self._video_info:
            self._pending_part_index = page
        # 刷新底部详情
        self._update_detail_display(page)

    def _update_detail_display(self, page: int):
        """根据选中的分P刷新底部信息"""
        # 从 video_info 中查找对应的 part
        part = next((p for p in self._video_info.parts if p.page == page), None) if self._video_info else None

        cid = part.cid if part else self.origin.target.cid
        title = self._video_info.title if self._video_info else self.origin.target.title
        bvid = self._video_info.bvid if self._video_info else self.origin.target.bvid
        part_text = self._part_combo.currentText()

        self._detail_title.setText(title or bvid)
        self._detail_bvid.setText(bvid)
        self._detail_part.setText(part_text)
        self._detail_cid.setText(str(cid))
        self._detail_url.setText(f"https://www.bilibili.com/video/{bvid}?p={page}")

    def _on_save(self):
        """保存编辑结果

        流程: 收集UI数据到 editing → 验证 editing → 通过后写回 origin
        """
        self._apply_target_changes()
        self._apply_danmaku_changes()

        # 验证任务数据
        error = self.editing.validate()
        if error:
            QMessageBox.warning(self, "任务错误", error)
            return

        # 验证配置数据
        if not self._validate_config():
            return

        # 全部验证通过，写回原始对象
        self.origin.apply_edit(self.editing)
        self.accept()

    def _apply_target_changes(self):
        """应用视频目标变更（如果有新选择）"""
        page = self._part_combo.currentData()
        if page is None or not self._video_info:
            return

        part = next((p for p in self._video_info.parts if p.page == page), None)
        if not part or not part.cid:
            return

        self.editing.target = VideoTarget(
            bvid=self._video_info.bvid,
            cid=part.cid,
            title=self._video_info.title,
        )
        self.editing.p_index = part.page
        self.editing.p_title = part.title

    def _apply_danmaku_changes(self):
        """应用弹幕文件变更（如果有新选择）"""
        if not self._selected_file:
            return

        parser = DanmakuParser()
        try:
            danmakus = parser.parse_xml_file(self._selected_file)
            if not danmakus:
                return

            self.editing.danmakus = danmakus
            self.editing.total = len(danmakus)
            self.editing.xml_path = self._selected_file
            if self.editing.status == TaskStatus.UNCONFIGURED:
                self.editing.status = TaskStatus.PENDING
        except Exception as e:
            logger.error(f"弹幕文件解析失败: {e}")

    def _validate_config(self) -> bool:
        """校验配置合法性，失败则弹出警告

        UIBinder 已实时更新到 editing.config_snapshot，如果有 Pydantic 验证错误，
        控件已经变红并设置了 tooltip。这里提取第一个错误信息显示给用户。
        """
        config_widgets: list[QWidget] = [
            self._min_delay, self._max_delay,
            self._burst_size, self._rest_min, self._rest_max,
            self._stop_count, self._stop_time,
            self._delay_between,
        ]
        for widget in config_widgets:
            if widget.property("invalid"):
                # tooltip 格式: "⚠️ 输入无效:\n{error_msg}"
                tooltip = widget.toolTip()
                error_msg = tooltip.split("\n", 1)[-1] if "\n" in tooltip else "配置值无效"
                QMessageBox.warning(self, "配置错误", error_msg)
                return False
        return True

    # --- 配置编辑 ---

    def _create_config_section(self) -> QWidget:
        group = QGroupBox("发送配置")
        layout = QVBoxLayout(group)

        config = self.editing.config_snapshot

        # --- 发送延迟 ---
        delay_group = QGroupBox("发送延迟")
        delay_form = QFormLayout(delay_group)

        delay_row = QHBoxLayout()
        delay_row.setSpacing(2)
        self._min_delay = QDoubleSpinBox()
        self._min_delay.setRange(0.1, 60.0)
        self._min_delay.setSingleStep(0.5)
        self._min_delay.setFixedWidth(70)
        UIBinder.bind(self._min_delay, config, "min_delay")
        delay_row.addWidget(self._min_delay)
        delay_row.addWidget(QLabel("-"))
        self._max_delay = QDoubleSpinBox()
        self._max_delay.setRange(0.1, 60.0)
        self._max_delay.setSingleStep(0.5)
        self._max_delay.setFixedWidth(70)
        UIBinder.bind(self._max_delay, config, "max_delay")
        delay_row.addWidget(self._max_delay)
        delay_row.addWidget(QLabel("秒"))
        delay_row.addStretch()
        delay_form.addRow("随机间隔:", delay_row)

        burst_row = QHBoxLayout()
        burst_row.setSpacing(2)
        self._burst_cb = QCheckBox("爆发模式")
        self._burst_cb.toggled.connect(self._on_burst_toggled)
        UIBinder.bind(self._burst_cb, config, "burst_enabled")
        burst_row.addWidget(self._burst_cb)
        burst_row.addWidget(QLabel("每"))
        self._burst_size = QSpinBox()
        self._burst_size.setRange(2, 100)
        self._burst_size.setFixedWidth(70)
        UIBinder.bind(self._burst_size, config, "burst_size")
        burst_row.addWidget(self._burst_size)
        burst_row.addWidget(QLabel("条，休息"))
        self._rest_min = QDoubleSpinBox()
        self._rest_min.setRange(0.0, 300.0)
        self._rest_min.setFixedWidth(60)
        UIBinder.bind(self._rest_min, config, "rest_min")
        burst_row.addWidget(self._rest_min)
        burst_row.addWidget(QLabel("-"))
        self._rest_max = QDoubleSpinBox()
        self._rest_max.setRange(0.0, 300.0)
        self._rest_max.setFixedWidth(60)
        UIBinder.bind(self._rest_max, config, "rest_max")
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
        UIBinder.bind(self._stop_count, config, "stop_after_count")
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
        UIBinder.bind(self._stop_time, config, "stop_after_time")
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
        UIBinder.bind(self._delay_between, config, "delay_between_tasks")
        queue_form.addRow("任务间隔:", self._delay_between)

        layout.addWidget(queue_group)

        # 初始化爆发控件状态
        self._on_burst_toggled(config.burst_enabled)

        return group

    def _on_burst_toggled(self, checked: bool):
        for ctrl in self._burst_controls:
            ctrl.setEnabled(checked)

    def _set_readonly_mode(self):
        """非可编辑状态时禁用所有编辑控件，只保留查看功能"""
        # 禁用视频目标编辑
        self._bv_input.setReadOnly(True)
        self._fetch_btn.setEnabled(False)
        self._part_combo.setEnabled(False)
        self._file_btn.setEnabled(False)

        # 禁用配置编辑
        config_widgets: list[QWidget] = [
            self._min_delay, self._max_delay,
            self._burst_cb, self._burst_size,
            self._rest_min, self._rest_max,
            self._stop_count, self._stop_time,
            self._delay_between,
        ]
        for widget in config_widgets:
            widget.setEnabled(False)

        # 隐藏保存按钮
        self._btn_save.setVisible(False)
