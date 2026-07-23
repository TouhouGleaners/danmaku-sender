from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QTabWidget,
    QSpinBox, QDoubleSpinBox, QFrame
)

from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.ui.framework.binder import UIBinder


class StrategySettingsTabs(QTabWidget):
    """策略设置区"""
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self._create_ui()

    def _create_ui(self):
        # Tab 1: 发送设置
        delay_tab = QWidget()
        delay_layout = QHBoxLayout(delay_tab)
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

        # 分隔线
        delay_layout.addSpacing(15)
        v_line = QFrame()
        v_line.setFrameShape(QFrame.Shape.VLine)
        v_line.setFrameShadow(QFrame.Shadow.Sunken)
        delay_layout.addWidget(v_line)
        delay_layout.addSpacing(15)

        # 爆发模式
        delay_layout.addWidget(QLabel("爆发模式: 每"))

        self.burst_size = QSpinBox()
        self.burst_size.setRange(0, 100)
        self.burst_size.setToolTip("0 或 1 表示关闭爆发模式")
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

        delay_layout.addStretch()
        self.addTab(delay_tab, "发送延迟")

        # Tab 2: 自动终止
        stop_tab = QWidget()
        stop_layout = QHBoxLayout(stop_tab)
        stop_layout.setContentsMargins(10, 20, 10, 20)

        # 数量限制
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

        # 时间限制
        stop_layout.addWidget(QLabel("已用时 >="))
        self.stop_time = QSpinBox()
        self.stop_time.setRange(0, 99999)
        stop_layout.addWidget(self.stop_time)
        stop_layout.addWidget(QLabel("分钟"))

        stop_layout.addStretch()
        stop_layout.addWidget(QLabel("(0为不限制)"))

        self.addTab(stop_tab, "自动终止")

    def init_bindings(self):
        """将 UI 控件与 AppState 进行双向绑定"""
        config = self.state.sender_config

        # 发送延迟策略
        UIBinder.bind(self.min_delay, config, "min_delay")
        UIBinder.bind(self.max_delay, config, "max_delay")

        # 爆发模式
        UIBinder.bind(self.burst_size, config, "burst_size")
        UIBinder.bind(self.burst_rest_min, config, "rest_min")
        UIBinder.bind(self.burst_rest_max, config, "rest_max")

        # 自动终止规则
        UIBinder.bind(self.stop_count, config, "stop_after_count")
        UIBinder.bind(self.stop_time, config, "stop_after_time")

    def set_inputs_locked(self, locked: bool):
        """供主控调用的防误触锁"""
        enabled = not locked

        self.min_delay.setEnabled(enabled)
        self.max_delay.setEnabled(enabled)
        self.burst_size.setEnabled(enabled)
        self.burst_rest_min.setEnabled(enabled)
        self.burst_rest_max.setEnabled(enabled)
        self.stop_count.setEnabled(enabled)
        self.stop_time.setEnabled(enabled)
