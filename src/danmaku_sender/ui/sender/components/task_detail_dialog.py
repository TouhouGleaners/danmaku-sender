from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QCheckBox, QSpinBox, QDoubleSpinBox, QPushButton, QGroupBox,
    QTextEdit, QFrame, QTabWidget, QWidget
)
from PySide6.QtCore import Qt

from danmaku_sender.types.models.queue import QueueTask
from danmaku_sender.config import SenderConfig


class TaskDetailDialog(QDialog):
    """任务详情与配置编辑弹窗"""

    def __init__(self, task: QueueTask, parent=None):
        super().__init__(parent)
        self.task = task
        self.setWindowTitle(f"任务详情 — {task.target.display_string}")
        self.setMinimumSize(500, 400)
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()

        # --- 详情 Tab ---
        detail_tab = QWidget()
        detail_layout = QVBoxLayout(detail_tab)
        detail_layout.addWidget(self._create_detail_section())
        tabs.addTab(detail_tab, "详情")

        # --- 配置 Tab ---
        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)
        config_layout.addWidget(self._create_config_section())
        tabs.addTab(config_tab, "发送配置")

        layout.addWidget(tabs)

        # --- 按钮 ---
        btn_layout = QHBoxLayout()
        self._btn_save = QPushButton("保存配置")
        self._btn_close = QPushButton("关闭")

        self._btn_save.clicked.connect(self.accept)
        self._btn_close.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self._btn_save)
        btn_layout.addWidget(self._btn_close)

        layout.addLayout(btn_layout)

    def _create_detail_section(self) -> QWidget:
        group = QGroupBox("任务信息")
        form = QFormLayout(group)

        task = self.task
        form.addRow("任务ID:", QLabel(task.task_id))
        form.addRow("视频:", QLabel(task.target.title or task.target.bvid))
        form.addRow("BVID:", QLabel(task.target.bvid))
        form.addRow("分P序号:", QLabel(f"P{task.p_index}"))
        form.addRow("分P标题:", QLabel(task.p_title or "-"))
        form.addRow("CID:", QLabel(str(task.target.cid)))
        form.addRow("状态:", QLabel(task.status.value))
        form.addRow("进度:", QLabel(f"{task.attempted}/{task.total}"))

        if task.error_msg:
            form.addRow("错误:", QLabel(task.error_msg))

        # 弹幕预览
        if task.danmakus:
            dm_preview = "\n".join(f"  {i+1}. {dm.msg}" for i, dm in enumerate(task.danmakus[:10]))
            if len(task.danmakus) > 10:
                dm_preview += f"\n  ... 共 {len(task.danmakus)} 条"
            preview = QTextEdit(dm_preview)
            preview.setReadOnly(True)
            preview.setMaximumHeight(120)
            form.addRow("弹幕预览:", preview)

        return group

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

        self._burst_controls = [self._burst_size, self._rest_min, self._rest_max]
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

        # 加载当前值
        self._load_values()

        return group

    def _load_values(self):
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
