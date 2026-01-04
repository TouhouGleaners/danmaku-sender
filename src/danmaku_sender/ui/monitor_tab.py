from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, 
    QLabel, QGroupBox, QTextEdit, QProgressBar, 
    QPushButton, QSpinBox, QFrame
)
from PySide6.QtCore import Qt


class MonitorTab(QWidget):
    def __init__(self):
        super().__init__()

        self._create_ui()

    def _create_ui(self):
        # 主布局 - 垂直布局
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- 监视状态与设置 ---
        settings_group = QGroupBox("监视状态与设置")
        settings_layout = QVBoxLayout()
        settings_layout.setContentsMargins(15, 15, 15, 15)

        # 当前视频详细信息
        info_layout = QFormLayout()
        info_layout.setLabelAlignment(Qt.AlignRight)
        info_layout.setVerticalSpacing(8)
        
        self.bvid_label = QLabel("尚未加载视频")
        self.bvid_label.setStyleSheet("font-weight: bold; color: #3498db;")
        
        self.part_label = QLabel("尚未选择分P")
        self.part_label.setStyleSheet("font-weight: bold; color: #3498db;")
        
        self.file_label = QLabel("尚未选择弹幕文件")
        self.file_label.setWordWrap(True)
        
        info_layout.addRow("当前视频:", self.bvid_label)
        info_layout.addRow("当前分P:", self.part_label)
        info_layout.addRow("本地文件:", self.file_label)
        
        settings_layout.addLayout(info_layout)
        
        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("margin: 5px 0;")
        settings_layout.addWidget(line)
        
        # 监视参数设置
        adv_layout = QHBoxLayout()
        
        adv_layout.addWidget(QLabel("检查间隔(秒):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 3600)
        self.interval_spin.setValue(60)
        self.interval_spin.setFixedWidth(80)
        adv_layout.addWidget(self.interval_spin)
        
        adv_layout.addSpacing(30)
        
        adv_layout.addWidget(QLabel("时间容差(ms):"))
        self.tolerance_spin = QSpinBox()
        self.tolerance_spin.setRange(0, 5000)
        self.tolerance_spin.setValue(500)
        self.tolerance_spin.setSingleStep(100)
        self.tolerance_spin.setFixedWidth(80)
        adv_layout.addWidget(self.tolerance_spin)
        
        adv_layout.addStretch()
        
        settings_layout.addLayout(adv_layout)
        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)

        
        # --- 运行日志区 ---
        log_group = QGroupBox("监视运行日志")
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(5, 10, 5, 5)
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("font-family: 'Consolas', 'Monaco', monospace; font-size: 12px;")
        
        log_layout.addWidget(self.log_output)
        log_group.setLayout(log_layout)
        
        main_layout.addWidget(log_group, stretch=1)

        # --- 底部控制栏 ---
        action_layout = QHBoxLayout()
        action_layout.setSpacing(15)
        
        self.status_label = QLabel("监视器：待命")
        self.status_label.setStyleSheet("color: #7f8c8d;")
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        
        self.start_btn = QPushButton("开始监视")
        self.start_btn.setFixedWidth(120)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        # 统一使用绿色的成功样式
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #2ecc71; 
                color: white; 
                font-weight: bold; 
                padding: 6px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #27ae60;
            }
        """)
        
        action_layout.addWidget(self.status_label)
        action_layout.addWidget(self.progress_bar, stretch=1)
        action_layout.addWidget(self.start_btn)
        
        main_layout.addLayout(action_layout)

        self.setLayout(main_layout)