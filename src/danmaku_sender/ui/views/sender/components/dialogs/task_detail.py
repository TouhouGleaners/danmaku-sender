import logging

from pydantic import ValidationError
from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from danmaku_sender.config import SenderConfig
from danmaku_sender.controller.video_controller import VideoController
from danmaku_sender.service.danmaku_parser import DanmakuParser
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.queue import TaskStatus, TaskView
from danmaku_sender.types.models.video import VideoInfo
from danmaku_sender.ui.framework.form_binder import DraftFormBinder
from danmaku_sender.utils.string_utils import parse_bilibili_link

logger = logging.getLogger(__name__)


class TaskDetailDialog(QDialog):
    """任务详情与配置编辑对话框。

    属于草稿修改表单：控件本身即草稿，确认保存时才写入模型，
    取消操作不会修改模型。

    Attributes:
        origin: 原始任务的只读视图，仅用于展示。
        editing: 保存时提交的 ``QueueTask``，在用户点击「保存」时组装完成。
    """

    def __init__(self, task: TaskView, api_auth, queue_active: bool = False, parent=None):
        super().__init__(parent)
        self.origin = task                  # 只读视图
        self.editing = task.to_draft()      # 保存载荷（保存那一刻才组装完）
        self._api_auth = api_auth
        self._video_info: VideoInfo | None = None
        self._pending_part_page: int | None = None
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
        # 配置区填充初始值（表单用可编辑的 SenderConfig，保存时再转回 TaskConfig）
        DraftFormBinder.fill(self, SenderConfig.from_task_config(self.editing.config_snapshot))

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
        bvid, page = parse_bilibili_link(raw)
        if not bvid:
            return
        self._bv_input.setText(bvid)
        self._pending_part_page = None
        # 链接带 ?p= 时用 page（1-based，同 part.page）定位
        if page is not None:
            self._pending_part_page = page
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

        if self._pending_part_page is not None:
            # 按 itemData（1-based page）匹配，不是 combo 行号
            target_index = next(
                (i for i in range(self._part_combo.count())
                 if self._part_combo.itemData(i) == self._pending_part_page),
                -1
            )
            if target_index >= 0:
                self._part_combo.setCurrentIndex(target_index)
        else:
            target_index = next(
                (i for i in range(self._part_combo.count())
                 if self._part_combo.itemData(i) == self.origin.p_index),
                0
            )
            self._part_combo.setCurrentIndex(target_index)

        self._pending_part_page = None

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
            self._pending_part_page = page
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

        流程: 读取控件值到 editing → 整体校验 → 通过后交调用方写回队列
        """
        self._apply_target_changes()
        self._apply_danmaku_changes()

        # 读取控件值并构造 SenderConfig（pydantic 校验，含跨字段规则），
        # 再冻结成工单参数快照
        try:
            collected = DraftFormBinder.collect(self, SenderConfig)
            self.editing.config_snapshot = collected.to_task_config()
        except ValidationError as e:
            rest = DraftFormBinder.show_errors(self, e)
            if rest:
                QMessageBox.warning(self, "配置错误", rest[0])
            return

        # 验证任务数据
        error = self.editing.validate()
        if error:
            QMessageBox.warning(self, "任务错误", error)
            return

        # 全部验证通过，由调用方通过 QueueState 应用修改
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
        DraftFormBinder.map(self._min_delay, "min_delay")
        delay_row.addWidget(self._min_delay)
        delay_row.addWidget(QLabel("-"))
        self._max_delay = QDoubleSpinBox()
        self._max_delay.setRange(0.1, 60.0)
        self._max_delay.setSingleStep(0.5)
        self._max_delay.setFixedWidth(70)
        DraftFormBinder.map(self._max_delay, "max_delay")
        delay_row.addWidget(self._max_delay)
        delay_row.addWidget(QLabel("秒"))
        delay_row.addStretch()
        delay_form.addRow("随机间隔:", delay_row)

        burst_row = QHBoxLayout()
        burst_row.setSpacing(2)
        self._burst_cb = QCheckBox("爆发模式")
        self._burst_cb.toggled.connect(self._on_burst_toggled)
        DraftFormBinder.map(self._burst_cb, "burst_enabled")
        burst_row.addWidget(self._burst_cb)
        burst_row.addWidget(QLabel("每"))
        self._burst_size = QSpinBox()
        self._burst_size.setRange(2, 100)
        self._burst_size.setFixedWidth(70)
        DraftFormBinder.map(self._burst_size, "burst_size")
        burst_row.addWidget(self._burst_size)
        burst_row.addWidget(QLabel("条，休息"))
        self._rest_min = QDoubleSpinBox()
        self._rest_min.setRange(0.0, 300.0)
        self._rest_min.setFixedWidth(60)
        DraftFormBinder.map(self._rest_min, "rest_min")
        burst_row.addWidget(self._rest_min)
        burst_row.addWidget(QLabel("-"))
        self._rest_max = QDoubleSpinBox()
        self._rest_max.setRange(0.0, 300.0)
        self._rest_max.setFixedWidth(60)
        DraftFormBinder.map(self._rest_max, "rest_max")
        burst_row.addWidget(self._rest_max)
        burst_row.addWidget(QLabel("秒"))
        burst_row.addStretch()
        delay_form.addRow(burst_row)

        self._burst_controls: list[QWidget] = [self._burst_size, self._rest_min, self._rest_max]
        layout.addWidget(delay_group)

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

        # 禁用配置编辑（队列级策略不在任务里，见 SendPolicy）
        config_widgets: list[QWidget] = [
            self._min_delay, self._max_delay,
            self._burst_cb, self._burst_size,
            self._rest_min, self._rest_max,
        ]
        for widget in config_widgets:
            widget.setEnabled(False)

        # 隐藏保存按钮
        self._btn_save.setVisible(False)
