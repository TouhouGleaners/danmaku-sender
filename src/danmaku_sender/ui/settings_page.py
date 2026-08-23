from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QCheckBox,
    QGroupBox, QSpinBox, QDoubleSpinBox, QFrame
)
from PySide6.QtCore import Qt

from .framework.binder import UIBinder

from danmaku_sender.runtime.state.app_state import AppState


class SettingsPage(QWidget):
    def __init__(self, state: AppState):
        super().__init__()

        self.state = state
        self._create_ui()

    def _create_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # --- 系统设置 ---
        system_group = QGroupBox("系统设置")
        system_layout = QFormLayout()

        self.prevent_sleep_checkbox = QCheckBox("任务运行时阻止电脑休眠")
        self.prevent_sleep_checkbox.setChecked(True)
        self.prevent_sleep_checkbox.setToolTip("保持网络和CPU运行，但允许屏幕关闭。")

        system_layout.addRow(self.prevent_sleep_checkbox)
        system_group.setLayout(system_layout)
        main_layout.addWidget(system_group)

        # --- 网络设置 ---
        network_group = QGroupBox("网络设置")
        network_layout = QFormLayout()

        self.proxy_checkbox = QCheckBox("使用系统代理")
        self.proxy_checkbox.setChecked(True)
        self.proxy_checkbox.setToolTip("启用后，程序将使用系统设置的代理服务器进行网络请求。")

        network_layout.addRow(self.proxy_checkbox)
        network_group.setLayout(network_layout)
        main_layout.addWidget(network_group)

        # --- 发送延迟 ---
        delay_group = QGroupBox("发送延迟")
        delay_layout = QHBoxLayout()
        delay_layout.setContentsMargins(10, 20, 10, 20)

        delay_layout.addWidget(QLabel("随机间隔(秒):"))
        self.min_delay = QDoubleSpinBox()
        self.min_delay.setRange(0.1, 60.0)
        self.min_delay.setValue(8.0)
        self.min_delay.setSingleStep(0.5)
        delay_layout.addWidget(self.min_delay)

        delay_layout.addWidget(QLabel("-"))

        self.max_delay = QDoubleSpinBox()
        self.max_delay.setRange(0.1, 60.0)
        self.max_delay.setValue(8.5)
        self.max_delay.setSingleStep(0.5)
        delay_layout.addWidget(self.max_delay)

        delay_layout.addSpacing(15)
        v_line = QFrame()
        v_line.setFrameShape(QFrame.Shape.VLine)
        v_line.setFrameShadow(QFrame.Shadow.Sunken)
        delay_layout.addWidget(v_line)
        delay_layout.addSpacing(15)

        self.burst_enabled_cb = QCheckBox("爆发模式")
        self.burst_enabled_cb.setToolTip("勾选启用爆发模式：每发 N 条后自动休息一段时间")
        self.burst_enabled_cb.toggled.connect(self._on_burst_toggled)
        delay_layout.addWidget(self.burst_enabled_cb)

        delay_layout.addWidget(QLabel("每"))

        self.burst_size = QSpinBox()
        self.burst_size.setRange(2, 100)
        self.burst_size.setValue(3)
        delay_layout.addWidget(self.burst_size)

        delay_layout.addWidget(QLabel("条，休息"))

        self.burst_rest_min = QDoubleSpinBox()
        self.burst_rest_min.setRange(0.0, 300.0)
        self.burst_rest_min.setValue(10.0)
        self.burst_rest_min.setFixedWidth(60)
        delay_layout.addWidget(self.burst_rest_min)

        delay_layout.addWidget(QLabel("-"))

        self.burst_rest_max = QDoubleSpinBox()
        self.burst_rest_max.setRange(0.0, 300.0)
        self.burst_rest_max.setValue(20.0)
        self.burst_rest_max.setFixedWidth(60)
        delay_layout.addWidget(self.burst_rest_max)

        delay_layout.addWidget(QLabel("秒"))

        self._burst_controls: list[QWidget] = [
            self.burst_size, self.burst_rest_min, self.burst_rest_max
        ]

        delay_layout.addStretch()
        delay_group.setLayout(delay_layout)
        main_layout.addWidget(delay_group)

        # --- 自动终止 ---
        stop_group = QGroupBox("自动终止")
        stop_layout = QHBoxLayout()
        stop_layout.setContentsMargins(10, 20, 10, 20)

        stop_layout.addWidget(QLabel("已发送 >="))
        self.stop_count = QSpinBox()
        self.stop_count.setRange(0, 99999)
        stop_layout.addWidget(self.stop_count)
        stop_layout.addWidget(QLabel("条"))

        stop_layout.addSpacing(20)
        v_line2 = QFrame()
        v_line2.setFrameShape(QFrame.Shape.VLine)
        v_line2.setFrameShadow(QFrame.Shadow.Sunken)
        stop_layout.addWidget(v_line2)
        stop_layout.addSpacing(20)

        stop_layout.addWidget(QLabel("已用时 >="))
        self.stop_time = QSpinBox()
        self.stop_time.setRange(0, 99999)
        stop_layout.addWidget(self.stop_time)
        stop_layout.addWidget(QLabel("分钟"))

        stop_layout.addStretch()
        stop_layout.addWidget(QLabel("(0为不限制)"))

        stop_group.setLayout(stop_layout)
        main_layout.addWidget(stop_group)

        main_layout.addStretch()

        info_label = QLabel("💡 账号管理请点击左上角头像区域。")
        info_label.setStyleSheet("color: gray; font-size: 12px;")
        main_layout.addWidget(info_label)

        self.setLayout(main_layout)

    def _on_burst_toggled(self, checked: bool):
        for ctrl in self._burst_controls:
            ctrl.setEnabled(checked)

    def init_bindings(self) -> None:
        """将 UI 控件与全局状态 (AppState) 进行双向绑定"""
        UIBinder.bind(self.prevent_sleep_checkbox, self.state.sender_config, "prevent_sleep", clear_old=True)
        UIBinder.bind(self.proxy_checkbox, self.state.sender_config, "use_system_proxy", clear_old=True)

        UIBinder.bind(self.prevent_sleep_checkbox, self.state.monitor_config, "prevent_sleep", clear_old=False)
        UIBinder.bind(self.proxy_checkbox, self.state.monitor_config, "use_system_proxy", clear_old=False)

        # 发送延迟策略
        config = self.state.sender_config
        UIBinder.bind(self.min_delay, config, "min_delay")
        UIBinder.bind(self.max_delay, config, "max_delay")
        UIBinder.bind(self.burst_enabled_cb, config, "burst_enabled")
        UIBinder.bind(self.burst_size, config, "burst_size")
        UIBinder.bind(self.burst_rest_min, config, "rest_min")
        UIBinder.bind(self.burst_rest_max, config, "rest_max")

        # 自动终止规则
        UIBinder.bind(self.stop_count, config, "stop_after_count")
        UIBinder.bind(self.stop_time, config, "stop_after_time")

        # 初始化爆发控件状态
        self._on_burst_toggled(self.burst_enabled_cb.isChecked())
