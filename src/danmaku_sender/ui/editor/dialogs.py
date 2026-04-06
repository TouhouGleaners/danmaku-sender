from typing import Any

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel, QPushButton,
    QComboBox, QSpinBox, QDoubleSpinBox, QGroupBox
)
from PySide6.QtCore import Qt, Slot

from .components import DanmakuPropertyForm
from ...core.entities.danmaku import Danmaku
from ...core.types.editor_types import EditorField


class EditDanmakuDialog(QDialog):
    """专业的全能弹幕编辑弹窗"""
    def __init__(self, dm: Danmaku, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑弹幕属性与内容")
        self.resize(450, 480)

        self.editor_widget = DanmakuPropertyForm()

        self._create_ui()
        self.editor_widget.load_danmaku(dm)

    def _create_ui(self):
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.CustomizeWindowHint
        )

        layout = QVBoxLayout(self)
        layout.addWidget(self.editor_widget)

        # 字数显示标签
        footer_layout = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: #7f8c8d; font-size: 12px;")
        footer_layout.addWidget(self.count_label)
        footer_layout.addStretch()

        # 操作按钮
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_ok = QPushButton("确定保存")
        self.btn_ok.setStyleSheet("background-color: #3498db; color: white; font-weight: bold;")
        self.btn_ok.clicked.connect(self.accept)

        footer_layout.addWidget(self.btn_cancel)
        footer_layout.addWidget(self.btn_ok)
        layout.addLayout(footer_layout)

        self.editor_widget.textChanged.connect(self._update_counter)

    @Slot(str)
    def _update_counter(self, text: str):
        """实时更新字数统计"""
        count = len(text)
        self.count_label.setText(f"当前字数: {count} / 100")
        if count > 100 or count == 0:
            self.count_label.setStyleSheet("color: #e74c3c; font-weight: bold; font-size: 12px;")
            self.btn_ok.setEnabled(False)
        else:
            self.count_label.setStyleSheet("color: #7f8c8d; font-size: 12px;")
            self.btn_ok.setEnabled(True)

    def get_properties(self) -> dict[EditorField, Any]:
        return self.editor_widget.get_properties()


class TimeOffsetDialog(QDialog):
    """时间轴平移对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("时间轴平移 / 补偿")
        self.setFixedSize(300, 180)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.CustomizeWindowHint
        )

        layout = QVBoxLayout(self)
        group = QGroupBox("设置偏移秒数")
        g_layout = QVBoxLayout(group)

        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-3600, 3600)
        self.offset_spin.setSuffix(" 秒")
        self.offset_spin.setDecimals(3)
        self.offset_spin.setValue(0.0)

        g_layout.addWidget(self.offset_spin)
        layout.addWidget(group)

        tips = QLabel("提示：正数向后推迟，负数提前。\n平移后会自动重新验证。")
        tips.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        layout.addWidget(tips)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_ok = QPushButton("确认应用")
        self.btn_ok.setStyleSheet("background-color: #00a1d6; color: white; font-weight: bold;")
        self.btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)

    def get_offset_ms(self) -> int:
        """获取转换后的毫秒值"""
        return int(self.offset_spin.value() * 1000)


class ArrayGeneratorDialog(QDialog):
    """弹幕阵列生成器对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("阵列生成器 (Array Creator)")
        self.setFixedSize(320, 280)
        self._create_ui()

    def _create_ui(self):
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.CustomizeWindowHint
        )

        layout = QVBoxLayout(self)

        # 提示文案
        tips = QLabel("将在选中弹幕的时间点之后，生成一组绚丽的弹幕列阵。")
        tips.setStyleSheet("color: #7f8c8d; font-size: 11px; margin-bottom: 10px;")
        tips.setWordWrap(True)
        layout.addWidget(tips)

        form = QFormLayout()

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("例如: 前方高能反应！")
        form.addRow("内容:", self.text_input)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("滚动", Danmaku.Mode.SCROLL.value)
        self.mode_combo.addItem("底端", Danmaku.Mode.BOTTOM.value)
        self.mode_combo.addItem("顶端", Danmaku.Mode.TOP.value)
        form.addRow("模式:", self.mode_combo)

        self.color_combo = QComboBox()
        self.color_combo.addItem("B 站原味循环", "classic")
        self.color_combo.addItem("HSV 丝滑彩虹", "rainbow")
        form.addRow("色彩:", self.color_combo)

        self.count_spin = QSpinBox()
        self.count_spin.setRange(2, 100)
        self.count_spin.setValue(10)
        self.count_spin.setSuffix(" 条")
        form.addRow("数量:", self.count_spin)

        layout.addLayout(form)
        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("开始生成")
        self.btn_ok.setStyleSheet("background-color: #8e44ad; color: white; font-weight: bold;") # 紫色，代表魔法/高级
        self.btn_ok.clicked.connect(self.accept)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)

    def get_params(self):
        return {
            "text": self.text_input.text().strip() or "测试弹幕",
            "mode": Danmaku.Mode(self.mode_combo.currentData()),
            "color_strategy": self.color_combo.currentData(),
            "count": self.count_spin.value(),
        }