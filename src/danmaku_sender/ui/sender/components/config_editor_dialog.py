from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QCheckBox, QSpinBox, QDoubleSpinBox, QPushButton, QGroupBox, QFrame
)
from PySide6.QtCore import Qt

from danmaku_sender.config import SenderConfig


class ConfigEditorDialog(QDialog):
    """发送配置编辑弹窗，用于编辑单个任务的配置快照"""

    def __init__(self, config: SenderConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑发送配置")
        self.setMinimumWidth(400)
        self._config = config.model_copy()
        self._create_ui()
        self._load_values()

    def _create_ui(self):
        layout = QVBoxLayout(self)

        # --- 发送延迟 ---
        delay_group = QGroupBox("发送延迟")
        delay_layout = QFormLayout(delay_group)

        delay_row = QHBoxLayout()
        self._min_delay = QDoubleSpinBox()
        self._min_delay.setRange(0.1, 60.0)
        self._min_delay.setSingleStep(0.5)
        delay_row.addWidget(self._min_delay)
        delay_row.addWidget(QLabel("-"))
        self._max_delay = QDoubleSpinBox()
        self._max_delay.setRange(0.1, 60.0)
        self._max_delay.setSingleStep(0.5)
        delay_row.addWidget(self._max_delay)
        delay_row.addWidget(QLabel("秒"))
        delay_layout.addRow("随机间隔:", delay_row)

        # 爆发模式
        self._burst_cb = QCheckBox("启用爆发模式")
        self._burst_cb.toggled.connect(self._on_burst_toggled)
        delay_layout.addRow(self._burst_cb)

        burst_row = QHBoxLayout()
        burst_row.addWidget(QLabel("每"))
        self._burst_size = QSpinBox()
        self._burst_size.setRange(2, 100)
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
        delay_layout.addRow(burst_row)

        self._burst_controls = [self._burst_size, self._rest_min, self._rest_max]
        layout.addWidget(delay_group)

        # --- 自动终止 ---
        stop_group = QGroupBox("自动终止")
        stop_layout = QFormLayout(stop_group)

        stop_count_row = QHBoxLayout()
        self._stop_count = QSpinBox()
        self._stop_count.setRange(0, 99999)
        stop_count_row.addWidget(self._stop_count)
        stop_count_row.addWidget(QLabel("条"))
        stop_count_row.addWidget(QLabel("(0为不限制)"))
        stop_layout.addRow("已发送 >=", stop_count_row)

        stop_time_row = QHBoxLayout()
        self._stop_time = QSpinBox()
        self._stop_time.setRange(0, 99999)
        stop_time_row.addWidget(self._stop_time)
        stop_time_row.addWidget(QLabel("分钟"))
        stop_time_row.addWidget(QLabel("(0为不限制)"))
        stop_layout.addRow("已用时 >=", stop_time_row)

        layout.addWidget(stop_group)

        # --- 队列设置 ---
        queue_group = QGroupBox("队列设置")
        queue_layout = QFormLayout(queue_group)

        self._delay_between = QDoubleSpinBox()
        self._delay_between.setRange(0.0, 300.0)
        self._delay_between.setSingleStep(5.0)
        queue_layout.addRow("任务间隔:", self._delay_between)

        layout.addWidget(queue_group)

        # --- 按钮 ---
        btn_layout = QHBoxLayout()
        self._btn_reset = QPushButton("恢复默认")
        self._btn_save = QPushButton("保存")
        self._btn_cancel = QPushButton("取消")

        self._btn_reset.clicked.connect(self._reset_to_defaults)
        self._btn_save.clicked.connect(self.accept)
        self._btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(self._btn_reset)
        btn_layout.addStretch()
        btn_layout.addWidget(self._btn_save)
        btn_layout.addWidget(self._btn_cancel)

        layout.addLayout(btn_layout)

    def _load_values(self):
        cfg = self._config
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

    def _reset_to_defaults(self):
        defaults = SenderConfig()
        self._min_delay.setValue(defaults.min_delay)
        self._max_delay.setValue(defaults.max_delay)
        self._burst_cb.setChecked(defaults.burst_enabled)
        self._burst_size.setValue(defaults.burst_size)
        self._rest_min.setValue(defaults.rest_min)
        self._rest_max.setValue(defaults.rest_max)
        self._stop_count.setValue(defaults.stop_after_count)
        self._stop_time.setValue(defaults.stop_after_time)
        self._delay_between.setValue(defaults.delay_between_tasks)

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
            prevent_sleep=self._config.prevent_sleep,
            use_system_proxy=self._config.use_system_proxy,
            skip_sent=self._config.skip_sent,
        )
