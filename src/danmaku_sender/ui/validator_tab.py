from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFrame
)
from PySide6.QtCore import Qt


class ValidatorTab(QWidget):
    def __init__(self):
        super().__init__()

        self._create_ui()

    def _create_ui(self):
        # 主布局 - 垂直布局
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- 顶部控制栏 ---
        top_layout = QHBoxLayout()

        self.run_btn = QPushButton("开始验证")
        self.run_btn.setFixedWidth(100)

        # 批量处理按钮
        self.batch_btn = QPushButton("批量验证")
        self.batch_btn.setFixedWidth(100)
        self.batch_btn.setEnabled(False)

        self.undo_btn = QPushButton("撤销")
        self.undo_btn.setFixedWidth(80)
        self.undo_btn.setEnabled(False)

        self.status_label = QLabel("提示: 请先在“发射器”页面加载文件并选择分P。")
        self.status_label.setStyleSheet("color: #7f8c8d;")

        top_layout.addWidget(self.run_btn)
        top_layout.addWidget(self.batch_btn)
        top_layout.addWidget(self.undo_btn)
        top_layout.addWidget(self.status_label, stretch=1)

        main_layout.addLayout(top_layout)

        # --- 中间表格区 ---
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["序号", "时间", "问题描述", "弹幕内容"])

        # 设置表格行为
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        # 设置列宽调整模式
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        main_layout.addWidget(self.table)

        # --- 底部按钮区 ---
        bottom_layout = QHBoxLayout()

        self.delete_btn = QPushButton("删除选中条目")
        self.delete_btn.setStyleSheet("color: #e74c3c;")
        self.delete_btn.setEnabled(False)

        self.apply_btn = QPushButton("应用所有修改")
        self.apply_btn.setStyleSheet("""
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
        self.apply_btn.setEnabled(False)

        bottom_layout.addWidget(self.delete_btn)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.apply_btn)

        main_layout.addLayout(bottom_layout)
        self.setLayout(main_layout)