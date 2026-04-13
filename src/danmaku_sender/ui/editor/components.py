from typing import Any, Callable

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal, Slot
from PySide6.QtGui import QColor, QBrush, QPainter, QPainterPath, QFont, QPen, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QPushButton,
    QLabel, QSizePolicy, QColorDialog, QLineEdit, QCheckBox,
    QGroupBox, QDoubleSpinBox, QComboBox, QTextEdit, QMessageBox
)

from ..framework.binder import UIBinder

from ...core.entities.danmaku import Danmaku
from ...core.state import AppState
from ...core.types.editor_types import EditorField
from ...utils.time_utils import format_duration


class EditorTableModel(QAbstractTableModel):
    HEADERS =["序号", "时间", "问题描述", "弹幕内容"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._view_items =[]

    def update_data(self, view_items):
        """全量刷新表格数据"""
        self.beginResetModel()
        self._view_items = view_items
        self.endResetModel()

    def get_item_id(self, row: int) -> str | None:
        """获取选中行对应的底层 UUID"""
        if 0 <= row < len(self._view_items):
            return self._view_items[row]['id']
        return None

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._view_items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int) -> str | None:
        if (
            orientation == Qt.Orientation.Horizontal and
            role == Qt.ItemDataRole.DisplayRole and
            0 <= section < len(self.HEADERS)
        ):
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()

        if not (0 <= row < len(self._view_items)):
            return None

        item = self._view_items[row]
        is_valid = item['is_valid']

        match role:
            case Qt.ItemDataRole.DisplayRole:
                # 提供显示文本
                match col:
                    case 0: return str(index.row() + 1)
                    case 1: return format_duration(item['time_ms'] / 1000)
                    case 2: return item['error_msg']
                    case 3: return item['content']
                    case _: return None

            case Qt.ItemDataRole.UserRole:
                # 提供 UserRole 用于反向查找
                return item['id']

            case Qt.ItemDataRole.ForegroundRole:
                # 提供颜色样式
                if is_valid:
                    return QBrush(QColor("#95a5a6"))  # 正常行的灰字

                # 错误行：仅针对“问题描述”列标红
                if col == 2:
                    return QBrush(QColor("#e74c3c"))  # 错误行的理由红字

            case Qt.ItemDataRole.BackgroundRole:
                # 错误行的淡红背景
                if not is_valid:
                    return QBrush(QColor("#fff2f2"))

            case _:
                return None

        return None


class ValidationRulesGroup(QGroupBox):
    """校验与过滤规则区"""
    def __init__(self, parent=None):
        super().__init__("校验与过滤规则", parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._state: AppState | None = None
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        sys_info = QLabel("系统规则: 限制长度(≤100字)、禁止换行、拦截特殊符号 (已默认开启)")
        sys_info.setStyleSheet("color: #95a5a6; font-size: 11px;")
        layout.addWidget(sys_info)

        keyword_layout = QHBoxLayout()
        self.enable_custom_checkbox = QCheckBox("关键词拦截:")
        self.enable_custom_checkbox.setToolTip("开启后将拦截包含以下关键词的弹幕")

        self.keywords_input = QLineEdit()
        self.keywords_input.setPlaceholderText("用中文或英文逗号分隔，如：应用, 过滤")

        keyword_layout.addWidget(self.enable_custom_checkbox)
        keyword_layout.addWidget(self.keywords_input, stretch=1)

        layout.addLayout(keyword_layout)

    def bind_state(self, state: AppState):
        """将 UI 控件与 AppState 进行双向绑定"""
        if self._state is state:
            return

        if self._state is not None:
            try:
                self.keywords_input.textChanged.disconnect()
                self.enable_custom_checkbox.stateChanged.disconnect()
            except (RuntimeError, TypeError):
                pass

        self._state = state
        config = state.validation_config

        # 通用控件绑定
        UIBinder.bind(self.enable_custom_checkbox, config, "enabled")

        # 复杂类型映射手动处理 (str <-> list[str])
        self.keywords_input.blockSignals(True)
        self.keywords_input.setText(", ".join(config.blocked_keywords))
        self.keywords_input.blockSignals(False)
        self.keywords_input.setEnabled(config.enabled)

        # 绑定关键词输入的信号与开关的联动状态
        self.keywords_input.textChanged.connect(self._on_keywords_changed)
        self.enable_custom_checkbox.stateChanged.connect(
            lambda val: self.keywords_input.setEnabled(bool(val))
        )

    def _on_keywords_changed(self, text: str):
        """处理关键词文本变更"""
        if not self._state:
            return

        raw_text = text.replace('，', ',').lower()
        parts = [k.strip() for k in raw_text.split(',') if k.strip()]
        unique_keywords = sorted(list(set(parts)))

        self._state.validation_config.blocked_keywords = unique_keywords


class DanmakuPropertyForm(QWidget):
    """模块内高度内聚的表单控件，用于 Inspector 和 Dialog 共享"""
    textChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_color_val = 16777215

        self._create_ui()
        self._init_bili_palette()
        self._connect_live_preview()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 预览组件
        self.preview_board = DanmakuPreviewWidget()
        layout.addWidget(self.preview_board)

        form_layout = QFormLayout()

        # 时间
        self.prop_time = QDoubleSpinBox()
        self.prop_time.setRange(0, 999999)
        self.prop_time.setDecimals(3)
        self.prop_time.setSuffix(" 秒")
        form_layout.addRow("出现时间:", self.prop_time)

        # 模式
        self.prop_mode = QComboBox()
        self.prop_mode.addItem("滚动 (1)", Danmaku.Mode.SCROLL)
        self.prop_mode.addItem("底端 (4)", Danmaku.Mode.BOTTOM)
        self.prop_mode.addItem("顶端 (5)", Danmaku.Mode.TOP)
        form_layout.addRow("弹幕模式:", self.prop_mode)

        # 字号
        self.prop_fontsize = QComboBox()
        self._populate_font_sizes()
        form_layout.addRow("弹幕字号:", self.prop_fontsize)

        # 颜色
        self.prop_color_btn = QPushButton()
        self.prop_color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prop_color_btn.setFixedHeight(24)
        self.prop_color_btn.clicked.connect(self._choose_color)
        form_layout.addRow("弹幕颜色:", self.prop_color_btn)

        layout.addLayout(form_layout)

        # 文本内容
        layout.addWidget(QLabel("弹幕内容:"))
        self.prop_text = QTextEdit()
        self.prop_text.setAcceptRichText(False)
        self.prop_text.textChanged.connect(lambda: self.textChanged.emit(self.get_cleaned_text()))
        layout.addWidget(self.prop_text)

    def _connect_live_preview(self):
        """将所有修改动作绑定到实时预览"""
        self.prop_text.textChanged.connect(self._trigger_preview_update)
        self.prop_mode.currentIndexChanged.connect(self._trigger_preview_update)
        self.prop_fontsize.currentIndexChanged.connect(self._trigger_preview_update)

    @Slot()
    def _trigger_preview_update(self, *args):
        """触发预览画板更新"""
        self.preview_board.update_preview(
            text=self.get_cleaned_text(),
            color=self.current_color_val,
            fontsize=self.prop_fontsize.currentData(),
            mode=self.prop_mode.currentData()
        )

    def _init_bili_palette(self):
        """将 Danmaku.Standards 中定义的标准色注入 QColorDialog"""
        for i, hex_color in enumerate(Danmaku.Standards.COLORS):
            QColorDialog.setCustomColor(i, QColor(hex_color))

    def _update_color_btn_style(self, hex_str: str):
        self.prop_color_btn.setStyleSheet(f"background-color: {hex_str}; border: 1px solid #bdc3c7; border-radius: 3px;")

    def _choose_color(self):
        """弹出调色板"""
        dialog = QColorDialog(self)
        dialog.setWindowTitle("选择弹幕颜色")
        dialog.setCurrentColor(QColor(f"#{self.current_color_val & 0xFFFFFF:06x}"))

        if dialog.exec() == QColorDialog.DialogCode.Accepted:
            color = dialog.currentColor()
            self.current_color_val = int(color.name().lstrip('#'), 16)
            self._update_color_btn_style(color.name())
            self._trigger_preview_update()

    def _populate_font_sizes(self, current_val: int | None = None):
        """统一填充字号选项"""
        self.prop_fontsize.blockSignals(True)
        self.prop_fontsize.clear()

        for text, value in Danmaku.Standards.FONT_SIZES.items():
            self.prop_fontsize.addItem(text, value)

        target = current_val if current_val is not None else 25
        idx = self.prop_fontsize.findData(target)

        if idx >= 0:
            self.prop_fontsize.setCurrentIndex(idx)
        else:
            self.prop_fontsize.addItem(f"自定义 ({target})", target)
            self.prop_fontsize.setCurrentIndex(self.prop_fontsize.count() - 1)

        self.prop_fontsize.blockSignals(False)

    def load_danmaku(self, dm: Danmaku):
        """将选中的弹幕数据加载到面板"""
        self.prop_time.blockSignals(True)
        self.prop_time.setValue(dm.progress / 1000.0)
        self.prop_time.blockSignals(False)

        mode_idx = self.prop_mode.findData(dm.mode)
        self.prop_mode.setCurrentIndex(mode_idx if mode_idx >= 0 else 0)

        self._populate_font_sizes(dm.fontsize)
        self.current_color_val = dm.color
        self._update_color_btn_style(f"#{self.current_color_val & 0xFFFFFF:06x}")

        self.prop_text.blockSignals(True)
        self.prop_text.setPlainText(dm.msg)
        self.prop_text.blockSignals(False)
        self.textChanged.emit(self.get_cleaned_text())
        self._trigger_preview_update()

    def clear_form(self):
        self.prop_time.setValue(0.0)
        self.prop_mode.setCurrentIndex(0)
        self._populate_font_sizes()
        self.current_color_val = 16777215
        self._update_color_btn_style("#ffffff")
        self.prop_text.clear()
        self._trigger_preview_update()

    def get_cleaned_text(self) -> str:
        return self.prop_text.toPlainText().replace('\n', '').replace('\r', '').strip()

    def get_properties(self) -> dict[EditorField, Any]:
        return {
            EditorField.PROGRESS: int(self.prop_time.value() * 1000),
            EditorField.MODE: self.prop_mode.currentData(),
            EditorField.FONT_SIZE: self.prop_fontsize.currentData(),
            EditorField.COLOR: self.current_color_val,
            EditorField.MSG: self.get_cleaned_text()
        }


class PropertyInspectorGroup(QGroupBox):
    """侧边栏属性检查器"""
    def __init__(self, parent=None):
        super().__init__("属性检查器", parent)
        self.on_save_callback: Callable[[dict[EditorField, Any]], None] | None = None
        self.editor_widget = DanmakuPropertyForm()

        self._create_ui()
        self.reset_inspector()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(self.editor_widget)

        self.prop_save_btn = QPushButton("保存属性修改")
        self.prop_save_btn.setStyleSheet("""
            QPushButton { background-color: #3498db; color: white; font-weight: bold; padding: 6px; border-radius: 4px; }
            QPushButton:hover { background-color: #2980b9; }
        """)
        self.prop_save_btn.clicked.connect(self._on_save_clicked)
        layout.addWidget(self.prop_save_btn)

    def load_danmaku(self, dm: Danmaku):
        self.setEnabled(True)
        self.editor_widget.load_danmaku(dm)

    def reset_inspector(self):
        self.setEnabled(False)
        self.editor_widget.clear_form()

    def _on_save_clicked(self):
        props = self.editor_widget.get_properties()
        if not props[EditorField.MSG]:
            QMessageBox.warning(self, "错误", "弹幕内容不能为空！如需删除请右键该条目进行删除。")
            return
        if self.on_save_callback:
            self.on_save_callback(props)


class DanmakuPreviewWidget(QWidget):
    """弹幕预览组件，负责在编辑器中实时渲染当前选中弹幕的样式"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(120)
        self.setStyleSheet("background-color: #1a1a1a; border-radius: 6px;")

        # 内部状态
        self._text = ""
        self._color_val = 16777215
        self._fontsize = 25
        self._mode = 1

    def update_preview(self, text: str, color: int, fontsize: int, mode: int):
        """接收最新属性并触发重绘"""
        self._text = text
        self._color_val = color
        self._fontsize = fontsize
        self._mode = mode
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)

        if not self._text:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        base_display_size = max(10, int(self._fontsize * 0.7))
        font = QFont("Microsoft YaHei", base_display_size)
        font.setBold(True)

        # 计算文字位置
        fm = QFontMetrics(font)
        text_width = fm.horizontalAdvance(self._text)

        rect = self.rect()
        max_allowed_width = rect.width() - 20

        scale_factor = 1.0
        if text_width > max_allowed_width:
            scale_factor = max_allowed_width / text_width

            new_size = max(6, int(base_display_size * scale_factor))
            font.setPointSize(new_size)

            fm = QFontMetrics(font)
            text_width = fm.horizontalAdvance(self._text)

        text_height = fm.ascent()

        x = (rect.width() - text_width) / 2

        match self._mode:
            case Danmaku.Mode.TOP:
                y = text_height + 15
            case Danmaku.Mode.BOTTOM:
                y = rect.height() - 15
            case Danmaku.Mode.SCROLL:
                y = (rect.height() + text_height) / 2 - 5
            case _:
                y = rect.center().y()

        # 构造文字路径
        path = QPainterPath()
        path.addText(x, y, font, self._text)

        # 绘制描边
        pen = QPen(QColor(0, 0, 0, 200))
        stroke_width = max(1.0, 2.0 * scale_factor)
        pen.setWidthF(stroke_width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        painter.setPen(pen)
        painter.drawPath(path)

        # 填充颜色
        painter.fillPath(path, QBrush(QColor(f"#{self._color_val & 0xFFFFFF:06x}")))

        painter.end()
