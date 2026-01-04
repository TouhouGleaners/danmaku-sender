from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QComboBox, QLabel, QGroupBox, QTextEdit,
    QProgressBar, QTabWidget, QSpinBox, QDoubleSpinBox, QFrame
)
from PySide6.QtCore import Qt


class SenderTab(QWidget):
    def __init__(self):
        super().__init__()

        self._create_ui()

    def _create_ui(self):
        # 主布局 - 垂直布局
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- 基础参数区 ---
        basic_group = QGroupBox("基础参数")
        basic_layout = QFormLayout()

        # BV + 获取按钮
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

        basic_layout.addRow(QLabel("视频BV号:"), bv_layout)
        basic_layout.addRow(QLabel("分P选择:"), self.part_combo)
        basic_layout.addRow(QLabel("弹幕文件:"), file_layout)

        basic_group.setLayout(basic_layout)
        main_layout.addWidget(basic_group)

        # --- 策略设置区 ---
        strategy_tabs = QTabWidget()

        # Tab 1: 发送设置
        delay_tab = QWidget()
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

        # 分隔线
        delay_layout.addSpacing(15)
        v_line = QFrame()
        v_line.setFrameShape(QFrame.VLine)
        v_line.setFrameShadow(QFrame.Sunken)
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
        
        delay_tab.setLayout(delay_layout)
        strategy_tabs.addTab(delay_tab, "发送延迟")

        # Tab 2: 自动终止
        stop_tab = QWidget()
        stop_layout = QHBoxLayout()
        stop_layout.setContentsMargins(10, 20, 10, 20)

        # 数量限制
        stop_layout.addWidget(QLabel("已发送 >="))
        self.stop_count = QSpinBox()
        self.stop_count.setRange(0, 99999)
        stop_layout.addWidget(self.stop_count)
        stop_layout.addWidget(QLabel("条"))

        stop_layout.addSpacing(20)
        v_line2 = QFrame()
        v_line2.setFrameShape(QFrame.VLine)
        v_line2.setFrameShadow(QFrame.Sunken)
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

        stop_tab.setLayout(stop_layout)
        strategy_tabs.addTab(stop_tab, "自动终止")

        main_layout.addWidget(strategy_tabs)

        # --- 日志区 ---
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout()
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)
        log_group.setLayout(log_layout)

        main_layout.addWidget(log_group, stretch=1)

        # --- 操作区 ---
        action_layout = QHBoxLayout()

        self.status_label = QLabel("发送器：待命")
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.start_btn = QPushButton("开始发送")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #2ecc71; 
                color: white; 
                font-weight: bold; 
                padding: 6px 20px;
                border-radius: 4px;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)

        action_layout.addWidget(self.status_label)
        action_layout.addWidget(self.progress_bar, stretch=1)
        action_layout.addWidget(self.start_btn)

        main_layout.addLayout(action_layout)

        self.setLayout(main_layout)