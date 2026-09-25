from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from danmaku_sender.config.theme_config import ThemeMode
from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.ui.framework.form_binder import LiveFormBinder


class SettingsPage(QWidget):
    """全局设置页。

    属于实时修改表单：无「保存」按钮，控件变更通过 LiveFormBinder
    立即写入配置模型。主题需要即时生效，因此在 ``after_write`` 中
    发射 ``themeApplied``。页面显示时调用 ``fill()`` 刷新控件值。
    """

    themeApplied = Signal(object)  # ThemeMode：主题已写入配置，可立即应用

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

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("跟随系统", ThemeMode.SYSTEM)
        self.theme_combo.addItem("浅色模式", ThemeMode.LIGHT)
        self.theme_combo.addItem("深色模式", ThemeMode.DARK)
        system_layout.addRow("界面主题:", self.theme_combo)

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

        # --- 队列设置 ---
        queue_group = QGroupBox("队列设置")
        queue_layout = QHBoxLayout()
        queue_layout.setContentsMargins(10, 20, 10, 20)

        queue_layout.addWidget(QLabel("任务间隔"))
        self.delay_between = QDoubleSpinBox()
        self.delay_between.setRange(0.0, 300.0)
        self.delay_between.setSingleStep(5.0)
        queue_layout.addWidget(self.delay_between)
        queue_layout.addWidget(QLabel("秒"))

        queue_layout.addSpacing(20)
        v_line2 = QFrame()
        v_line2.setFrameShape(QFrame.Shape.VLine)
        v_line2.setFrameShadow(QFrame.Shadow.Sunken)
        queue_layout.addWidget(v_line2)
        queue_layout.addSpacing(20)

        queue_layout.addWidget(QLabel("已发送 >="))
        self.stop_count = QSpinBox()
        self.stop_count.setRange(0, 99999)
        queue_layout.addWidget(self.stop_count)
        queue_layout.addWidget(QLabel("条"))

        queue_layout.addSpacing(20)
        v_line3 = QFrame()
        v_line3.setFrameShape(QFrame.Shape.VLine)
        v_line3.setFrameShadow(QFrame.Shadow.Sunken)
        queue_layout.addWidget(v_line3)
        queue_layout.addSpacing(20)

        queue_layout.addWidget(QLabel("已用时 >="))
        self.stop_time = QSpinBox()
        self.stop_time.setRange(0, 99999)
        queue_layout.addWidget(self.stop_time)
        queue_layout.addWidget(QLabel("分钟"))

        queue_layout.addStretch()
        queue_layout.addWidget(QLabel("(0为不限制)"))

        queue_group.setLayout(queue_layout)
        main_layout.addWidget(queue_group)

        # --- 断点续传 ---
        resume_group = QGroupBox("断点续传")
        resume_layout = QFormLayout()

        self.skip_sent_cb = QCheckBox("跳过已发送的弹幕（基于历史记录去重）")
        self.skip_sent_cb.setToolTip("启用后，发送前会查询历史记录，自动跳过已成功发送过的弹幕。")

        resume_layout.addRow(self.skip_sent_cb)
        resume_group.setLayout(resume_layout)
        main_layout.addWidget(resume_group)

        main_layout.addStretch()

        info_label = QLabel("💡 账号管理请点击左上角头像区域。")
        info_label.setStyleSheet("color: gray; font-size: 12px;")
        main_layout.addWidget(info_label)

        self.setLayout(main_layout)

    def _on_burst_toggled(self, checked: bool):
        for ctrl in self._burst_controls:
            ctrl.setEnabled(checked)

    @Slot(str, object)
    def _on_config_written(self, _field: str, _value: object) -> None:
        """配置写回成功 → 广播变更，由 MainWindow 防抖落盘。"""
        self.state.configChanged.emit()

    @Slot(str, object)
    def _on_theme_written(self, _field: str, value: object) -> None:
        """主题写回成功 → 广播变更并立刻应用主题。"""
        self.state.configChanged.emit()
        self.themeApplied.emit(value)

    def init_bindings(self) -> None:
        """将 UI 控件与全局状态 (AppState) 进行单向写绑定"""
        # 主题：写成功后立刻广播，驱动 ThemeService 应用
        LiveFormBinder.bind(
            self.theme_combo,
            self.state.theme_config,
            "theme_mode",
            after_write=self._on_theme_written,
        )

        # 全局系统设置（跨发送器/监视器共享，单绑一份）
        LiveFormBinder.bind(self.prevent_sleep_checkbox, self.state.global_config, "prevent_sleep", after_write=self._on_config_written)
        LiveFormBinder.bind(self.proxy_checkbox, self.state.global_config, "use_system_proxy", after_write=self._on_config_written)

        # 发送延迟策略
        config = self.state.sender_config
        LiveFormBinder.bind(self.min_delay, config, "min_delay", after_write=self._on_config_written)
        LiveFormBinder.bind(self.max_delay, config, "max_delay", after_write=self._on_config_written)
        LiveFormBinder.bind(self.burst_enabled_cb, config, "burst_enabled", after_write=self._on_config_written)
        LiveFormBinder.bind(self.burst_size, config, "burst_size", after_write=self._on_config_written)
        LiveFormBinder.bind(self.burst_rest_min, config, "rest_min", after_write=self._on_config_written)
        LiveFormBinder.bind(self.burst_rest_max, config, "rest_max", after_write=self._on_config_written)

        # 队列运行策略（一次队列运行共享，不随单个任务走）
        policy = self.state.send_policy
        LiveFormBinder.bind(self.delay_between, policy, "delay_between_tasks", after_write=self._on_config_written)
        LiveFormBinder.bind(self.stop_count, policy, "stop_after_count", after_write=self._on_config_written)
        LiveFormBinder.bind(self.stop_time, policy, "stop_after_time", after_write=self._on_config_written)
        LiveFormBinder.bind(self.skip_sent_cb, policy, "skip_sent", after_write=self._on_config_written)

    def showEvent(self, event):
        """打开页面时从状态重读控件值（无隐式同步）"""
        super().showEvent(event)
        LiveFormBinder.fill(self)
