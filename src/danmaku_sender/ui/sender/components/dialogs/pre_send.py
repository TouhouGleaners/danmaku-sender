from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout, QWidget,
    QPushButton, QLabel, QGroupBox, QCheckBox,
    QSpinBox, QDoubleSpinBox, QDialog
)
from PySide6.QtCore import Qt

from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.ui.framework.binder import UIBinder


class PreSendDialog(QDialog):
    """发送前确认对话框：集中展示目标视频、弹幕统计、账号信息和发送策略"""

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self._config_copy = state.sender_config.model_copy()

        self.setWindowTitle("发送确认")
        self.setMinimumWidth(420)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(self._create_video_section())
        layout.addWidget(self._create_danmaku_section())
        layout.addWidget(self._create_account_section())
        layout.addWidget(self._create_strategy_section())
        layout.addLayout(self._create_buttons())

    # region Sections

    def _create_video_section(self) -> QGroupBox:
        """目标视频信息"""
        group = QGroupBox("目标视频")
        form = QFormLayout(group)
        vs = self.state.video_state

        form.addRow("BV号:", QLabel(vs.bvid))
        form.addRow("标题:", QLabel(vs.video_title))
        if vs.selected_part_name:
            form.addRow("分P:", QLabel(vs.selected_part_name))

        return group

    def _create_danmaku_section(self) -> QGroupBox:
        """弹幕统计概览"""
        group = QGroupBox("弹幕信息")
        layout = QHBoxLayout(group)
        vs = self.state.video_state

        total = len(vs.loaded_danmakus)
        valid = sum(1 for d in vs.loaded_danmakus if d.is_valid is not False)
        invalid = sum(1 for d in vs.loaded_danmakus if d.is_valid is False)

        layout.addWidget(QLabel(f"总数: {total} 条"))
        layout.addWidget(QLabel(f"有效: {valid} 条"))

        if invalid > 0:
            warn_label = QLabel(f"无效: {invalid} 条")
            warn_label.setStyleSheet("color: #e74c3c;")
            layout.addWidget(warn_label)

        layout.addStretch()
        return group

    def _create_account_section(self) -> QGroupBox:
        """当前登录账号"""
        group = QGroupBox("当前账号")
        layout = QHBoxLayout(group)

        account_name = "未知"
        for acc in self.state.saved_accounts:
            if acc.sessdata == self.state.sessdata:
                account_name = acc.name or "未命名"
                break

        sessdata = self.state.sessdata or ""
        if len(sessdata) > 8:
            masked = sessdata[:4] + "****" + sessdata[-4:]
        elif sessdata:
            masked = "****"
        else:
            masked = "(未登录)"

        layout.addWidget(QLabel(f"{account_name} (SESSDATA: {masked})"))
        layout.addStretch()
        return group

    def _create_strategy_section(self) -> QGroupBox:
        """发送策略设置（绑定到临时拷贝，取消时自动丢弃）"""
        group = QGroupBox("发送策略")
        form = QFormLayout(group)
        config = self._config_copy

        # 随机间隔
        delay_layout = QHBoxLayout()
        self.min_delay = QDoubleSpinBox()
        self.min_delay.setRange(0.1, 60.0)
        self.min_delay.setSingleStep(0.5)
        delay_layout.addWidget(self.min_delay)
        delay_layout.addWidget(QLabel("~"))
        self.max_delay = QDoubleSpinBox()
        self.max_delay.setRange(0.1, 60.0)
        self.max_delay.setSingleStep(0.5)
        delay_layout.addWidget(self.max_delay)
        delay_layout.addWidget(QLabel("秒"))
        delay_layout.addStretch()
        form.addRow("随机间隔:", delay_layout)

        # 爆发模式
        self.burst_enabled_cb = QCheckBox("启用爆发模式")
        self.burst_enabled_cb.setToolTip("勾选后每发 N 条自动休息一段时间")
        self.burst_enabled_cb.toggled.connect(self._on_burst_toggled)
        form.addRow("", self.burst_enabled_cb)

        burst_layout = QHBoxLayout()
        self.burst_size = QSpinBox()
        self.burst_size.setRange(2, 100)
        self.burst_size.setValue(3)
        burst_layout.addWidget(QLabel("每"))
        burst_layout.addWidget(self.burst_size)
        burst_layout.addWidget(QLabel("条，休息"))
        self.burst_rest_min = QDoubleSpinBox()
        self.burst_rest_min.setRange(0.0, 300.0)
        self.burst_rest_min.setFixedWidth(60)
        burst_layout.addWidget(self.burst_rest_min)
        burst_layout.addWidget(QLabel("~"))
        self.burst_rest_max = QDoubleSpinBox()
        self.burst_rest_max.setRange(0.0, 300.0)
        self.burst_rest_max.setFixedWidth(60)
        burst_layout.addWidget(self.burst_rest_max)
        burst_layout.addWidget(QLabel("秒"))
        burst_layout.addStretch()
        form.addRow("爆发参数:", burst_layout)

        self._burst_controls: list[QWidget] = [self.burst_size, self.burst_rest_min, self.burst_rest_max]

        # 自动停止
        stop_layout = QHBoxLayout()
        self.stop_count = QSpinBox()
        self.stop_count.setRange(0, 99999)
        stop_layout.addWidget(QLabel("发满"))
        stop_layout.addWidget(self.stop_count)
        stop_layout.addWidget(QLabel("条"))
        stop_layout.addSpacing(12)
        self.stop_time = QSpinBox()
        self.stop_time.setRange(0, 99999)
        stop_layout.addWidget(QLabel("运行满"))
        stop_layout.addWidget(self.stop_time)
        stop_layout.addWidget(QLabel("分钟 (0=不限)"))
        stop_layout.addStretch()
        form.addRow("自动停止:", stop_layout)

        # 断点续传
        self.skip_sent_cb = QCheckBox("启用断点续传")
        form.addRow("", self.skip_sent_cb)

        # 绑定到临时拷贝
        UIBinder.bind(self.min_delay, config, "min_delay")
        UIBinder.bind(self.max_delay, config, "max_delay")
        UIBinder.bind(self.burst_enabled_cb, config, "burst_enabled")
        UIBinder.bind(self.burst_size, config, "burst_size")
        UIBinder.bind(self.burst_rest_min, config, "rest_min")
        UIBinder.bind(self.burst_rest_max, config, "rest_max")
        UIBinder.bind(self.stop_count, config, "stop_after_count")
        UIBinder.bind(self.stop_time, config, "stop_after_time")
        UIBinder.bind(self.skip_sent_cb, config, "skip_sent")

        # 初始化爆发控件状态
        self._on_burst_toggled(config.burst_enabled)

        return group

    def _on_burst_toggled(self, checked: bool):
        """爆发模式开关切换时，启用/禁用相关控件"""
        for ctrl in self._burst_controls:
            ctrl.setEnabled(checked)

    def _create_buttons(self) -> QHBoxLayout:
        """底部确认/取消按钮"""
        layout = QHBoxLayout()
        layout.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        confirm_btn = QPushButton("确认发送")
        confirm_btn.setObjectName("primaryButton")
        confirm_btn.clicked.connect(self._on_confirm)
        layout.addWidget(confirm_btn)

        return layout

    # endregion

    def _on_confirm(self):
        """确认时将临时拷贝写回全局配置"""
        for field in type(self._config_copy).model_fields:
            setattr(self.state.sender_config, field, getattr(self._config_copy, field))
        self.accept()
