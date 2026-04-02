import logging
from typing import Any, Callable

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSizePolicy,
    QTableView, QHeaderView, QAbstractItemView, QColorDialog,
    QMessageBox, QMenu, QLineEdit, QFrame, QCheckBox, QGroupBox,
    QSplitter, QFormLayout, QDoubleSpinBox, QComboBox, QTextEdit
)

from .dialogs import EditDanmakuDialog, TimeOffsetDialog
from .framework.binder import UIBinder

from ..core.engines.editor_session import EditorSession, EditorField
from ..core.models.danmaku import Danmaku
from ..core.state import AppState
from ..utils.time_utils import format_ms_to_hhmmss


class EditorTableModel(QAbstractTableModel):
    HEADERS = ["序号", "时间", "问题描述", "弹幕内容"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._view_items = []

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
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < len(self.HEADERS)
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
                    case 1: return format_ms_to_hhmmss(item['time_ms'])
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
        self.keywords_input.setStyleSheet("padding: 2px 5px;")

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

        # 通用控件交由 UIBinder 自动管理
        UIBinder.bind(self.enable_custom_checkbox, config, "enabled")

        # 复杂类型映射保留手动处理 (str <-> list[str])
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


class PropertyInspectorGroup(QGroupBox):
    """属性检查器"""
    def __init__(self, parent=None):
        super().__init__("属性检查器", parent)
        self.current_color_val = 16777215
        self.on_save_callback: Callable[[dict[EditorField, Any]], None] | None = None

        self._create_ui()
        self._init_bili_palette()
        self.reset_inspector()

    def _create_ui(self):
        prop_layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # 时间
        self.prop_time = QDoubleSpinBox()
        self.prop_time.setRange(0, 999999)
        self.prop_time.setDecimals(3)
        self.prop_time.setSuffix(" 秒")
        form_layout.addRow("出现时间:", self.prop_time)

        # 模式
        self.prop_mode = QComboBox()
        self.prop_mode.addItem("滚动 (1)", 1)
        self.prop_mode.addItem("底端 (4)", 4)
        self.prop_mode.addItem("顶端 (5)", 5)
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
        self.current_color_val = 16777215
        form_layout.addRow("弹幕颜色:", self.prop_color_btn)

        prop_layout.addLayout(form_layout)

        # 文本内容
        prop_layout.addWidget(QLabel("弹幕内容:"))
        self.prop_text = QTextEdit()
        self.prop_text.setAcceptRichText(False)
        prop_layout.addWidget(self.prop_text)

        # 保存修改按钮
        self.prop_save_btn = QPushButton("保存属性修改")
        self.prop_save_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                font-weight: bold;
                padding: 6px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #2980b9; }
        """)
        self.prop_save_btn.clicked.connect(self._on_save_clicked)
        prop_layout.addWidget(self.prop_save_btn)

    def _init_bili_palette(self):
        """将 Danmaku.Standards 中定义的标准色注入 QColorDialog"""
        for i, hex_color in enumerate(Danmaku.Standards.COLORS):
            QColorDialog.setCustomColor(i, QColor(hex_color))

    def int_to_hex(self, color_int: int) -> str:
        return f"#{color_int & 0xFFFFFF:06x}"

    def hex_to_int(self, hex_str: str) -> int:
        return int(hex_str.lstrip('#'), 16)

    def _update_color_btn_style(self, hex_str: str):
        self.prop_color_btn.setStyleSheet(
            f"background-color: {hex_str}; border: 1px solid #bdc3c7; border-radius: 3px;"
        )

    def _choose_color(self):
        """弹出调色板"""
        dialog = QColorDialog(self)
        dialog.setWindowTitle("选择弹幕颜色")
        dialog.setCurrentColor(QColor(self.int_to_hex(self.current_color_val)))

        if dialog.exec() == QColorDialog.DialogCode.Accepted:
            color = dialog.currentColor()
            self.current_color_val = self.hex_to_int(color.name())
            self._update_color_btn_style(color.name())

    def _populate_font_sizes(self, current_val: int | None = None):
        """统一填充字号选项"""
        self.prop_fontsize.blockSignals(True)
        self.prop_fontsize.clear()

        standards = Danmaku.Standards.FONT_SIZES
        for text, value in standards.items():
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
        self.setEnabled(True)
        self.prop_time.blockSignals(True)
        self.prop_time.setValue(dm.progress / 1000.0)
        self.prop_time.blockSignals(False)

        mode_idx = self.prop_mode.findData(dm.mode)
        self.prop_mode.setCurrentIndex(mode_idx if mode_idx >= 0 else 0)

        self._populate_font_sizes(dm.fontsize)
        self.current_color_val = dm.color
        self._update_color_btn_style(self.int_to_hex(dm.color))

        self.prop_text.setPlainText(dm.msg)

    def reset_inspector(self):
        """重置面板到未激活状态"""
        self.setEnabled(False)
        self.prop_text.clear()

        self.prop_time.blockSignals(True)
        self.prop_time.setValue(0.0)
        self.prop_time.blockSignals(False)

        self.prop_mode.setCurrentIndex(0)
        self._populate_font_sizes()

        self.current_color_val = 16777215
        self._update_color_btn_style("#ffffff")

    def _on_save_clicked(self):
        """保存弹幕属性修改"""
        clean_text = self.prop_text.toPlainText().replace('\n', '').replace('\r', '').strip()
        if not clean_text:
            QMessageBox.warning(self, "错误", "弹幕内容不能为空！如需删除请点击下方的删除按钮。")
            return

        new_props: dict[EditorField, Any] = {
            EditorField.PROGRESS: int(self.prop_time.value() * 1000),
            EditorField.MODE: self.prop_mode.currentData(),
            EditorField.FONT_SIZE: self.prop_fontsize.currentData(),
            EditorField.COLOR: self.current_color_val,
            EditorField.MSG: clean_text
        }
        if self.on_save_callback:
            self.on_save_callback(new_props)


class EditorPage(QWidget):
    def __init__(self):
        super().__init__()
        self._state: AppState | None = None
        self.session: EditorSession | None = None
        self.logger = logging.getLogger("App.System.UI.Editor")

        self.current_editing_index: str | None = None

        self._create_ui()

    def _create_ui(self):
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- 规则管理区 ---
        self.rules_group = ValidationRulesGroup()
        main_layout.addWidget(self.rules_group)

        # --- 顶部控制栏 ---
        top_layout = QHBoxLayout()

        self.run_btn = QPushButton("开始验证")
        self.run_btn.setFixedWidth(100)
        self.run_btn.clicked.connect(self.run_validation)

        # 批量处理按钮
        self.batch_btn = QPushButton("批量修复")
        self.batch_btn.setFixedWidth(100)
        self.batch_btn.setEnabled(False)

        # 时间轴偏移
        self.offset_btn = QPushButton("时间平移")
        self.offset_btn.setEnabled(False)
        self.offset_btn.setToolTip("在已加载弹幕的基础上，整体平移时间轴。")
        self.offset_btn.clicked.connect(self.open_offset_dialog)

        # 创建下拉菜单
        self.batch_menu = QMenu(self)
        self.batch_menu.addAction("一键去除所有换行符", self.batch_remove_newlines)
        self.batch_menu.addAction("一键截断过长弹幕(>100字)", self.batch_truncate_length)
        self.batch_btn.setMenu(self.batch_menu)

        # 撤销
        self.undo_btn = QPushButton("撤销")
        self.undo_btn.setFixedWidth(80)
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self.undo)

        # 预览切换
        self.preview_mode_cb = QCheckBox("预览模式 (全量显示)")
        self.preview_mode_cb.setToolTip("开启后显示所有弹幕，正常的弹幕将以灰色显示。")
        self.preview_mode_cb.stateChanged.connect(self._refresh_table)

        # 分隔线
        v_line = QFrame()
        v_line.setFrameShape(QFrame.Shape.VLine)
        v_line.setFrameShadow(QFrame.Shadow.Sunken)

        top_layout.addWidget(self.run_btn)
        top_layout.addWidget(self.batch_btn)
        top_layout.addWidget(self.offset_btn)
        top_layout.addWidget(self.undo_btn)
        top_layout.addSpacing(10)
        top_layout.addWidget(v_line)
        top_layout.addSpacing(10)
        top_layout.addWidget(self.preview_mode_cb)

        top_layout.addStretch()

        main_layout.addLayout(top_layout)

        # --- 核心区 ---
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- 左侧：表格 ---
        self.table = QTableView()
        self.model = EditorTableModel()
        self.table.setModel(self.model)

        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)

        # 将表格选择变更连接到右侧属性面板
        self.table.doubleClicked.connect(self.on_table_double_click)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_context_menu)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        self.splitter.addWidget(self.table)

        # --- 右侧：属性检查器面板 ---
        self.inspector_group = PropertyInspectorGroup()
        self.inspector_group.on_save_callback = self._apply_properties
        self.splitter.addWidget(self.inspector_group)

        # 设置比例 7:3
        self.splitter.setStretchFactor(0, 7)
        self.splitter.setStretchFactor(1, 3)

        main_layout.addWidget(self.splitter, stretch=1)

        # --- 底部按钮与状态区 ---
        bottom_layout = QHBoxLayout()

        self.delete_btn = QPushButton("删除选中条目")
        self.delete_btn.setStyleSheet("color: #e74c3c;")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self.delete_selected_items)

        self.status_label = QLabel("提示: 请先在“发射器”页面加载文件并选择分P。")
        self.status_label.setStyleSheet("color: #7f8c8d;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

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
        self.apply_btn.clicked.connect(self.apply_changes)

        bottom_layout.addWidget(self.delete_btn)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.status_label)
        bottom_layout.addSpacing(10)
        bottom_layout.addWidget(self.apply_btn)

        main_layout.addLayout(bottom_layout)

        self._update_ui_state()

    def bind_state(self, state: AppState):
        """将 UI 控件与 AppState 进行双向绑定"""
        if self._state is state:
            return

        self._state = state
        self.session = EditorSession(state)

        self.rules_group.bind_state(state)

        self._update_ui_state()

    # --- 辅助与状态管理 ---
    def _get_danmaku_for_row(self, row: int) -> tuple[str | None, Danmaku | None]:
        """辅助方法：通过 UI 行号获取底层 UUID 与弹幕对象"""
        if not self.session:
            return None, None

        item_id = self.model.get_item_id(row)
        if not item_id:
            return None, None

        item = self.session.items.get(item_id)
        if not item:
            return None, None

        return item_id, item.working

    def _update_ui_state(self):
        """统一状态机控制"""
        if not self._state:
            for btn in [self.run_btn, self.batch_btn, self.undo_btn,
                        self.delete_btn, self.apply_btn, self.offset_btn]:
                btn.setEnabled(False)
            return

        has_file = len(self._state.video_state.loaded_danmakus) > 0
        has_cid = self._state.video_state.selected_cid is not None
        self.run_btn.setEnabled(has_file and has_cid)

        if not self.session:
            return

        session_active = self.session.has_active_session
        has_items = self.model.rowCount() > 0

        self.offset_btn.setEnabled(session_active)
        self.batch_btn.setEnabled(session_active and has_items)
        self.delete_btn.setEnabled(session_active and self.table.selectionModel().hasSelection())

        self.undo_btn.setEnabled(self.session.can_undo)
        self.apply_btn.setEnabled(self.session.is_dirty)

        # --- 状态文案与样式切换 ---
        if self.session.is_dirty:
            self.status_label.setText("⚠️ 有未应用的修改！请点击“应用所有修改”按钮。")
            self.status_label.setStyleSheet("color: #d35400;")
        elif session_active:
            if has_items:
                # 统计未删除的错误
                count = self.session.active_error_count
                self.status_label.setText(f"❌ 发现 {count} 条问题弹幕，请处理。")
                self.status_label.setStyleSheet("color: red;")
            else:
                self.status_label.setText("✅ 当前无问题弹幕。")
                self.status_label.setStyleSheet("color: green;")
        else:
            self.status_label.setText("提示: 请先在“发射器”页面加载文件并选择分P。")
            self.status_label.setStyleSheet("color: #7f8c8d;")

    # --- 核心交互逻辑 ---
    def run_validation(self):
        """运行验证逻辑"""
        if not self._state or not self.session:
            return

        # 校验前置条件
        if not self._state.video_state.loaded_danmakus:
            QMessageBox.warning(self, "无法验证", "请先在 “发射器” 页面加载弹幕文件。")
            return

        if not self._state.video_state.selected_cid:
            QMessageBox.warning(self, "无法验证", "请先在 “发射器” 页面选择一个分P（用于检查时间戳）。")
            return

        duration = self._state.video_state.selected_part_duration_ms
        if duration <= 0:
            QMessageBox.warning(self, "数据缺失", "当前分P时长无效，无法进行时间戳校验。\n请尝试重新获取分P信息。")
            return

        # 检查未保存修改
        if self.session.is_dirty:
            reply = QMessageBox.question(
                self,
                "确认",
                "当前有未应用的修改，重新验证将丢弃这些修改。\n是否继续？",
                buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        # 执行验证
        self.status_label.setText("正在验证...")
        self.status_label.setStyleSheet("color: blue;")

        self.current_editing_index = None
        self.inspector_group.reset_inspector()
        has_issues = self.session.checkout_from_state()

        if not has_issues:
            QMessageBox.information(self, "验证通过", "所有弹幕均符合规范！")

        self._refresh_table()

    def _refresh_table(self):
        """刷新表格"""
        if not self.session:
            return

        items = self.session.generate_view_model(show_all=self.preview_mode_cb.isChecked())
        self.model.update_data(items)
        self._update_ui_state()

    def _on_selection_changed(self):
        """当表格选中项变化时，同步更新 UI 状态并渲染属性面板"""
        self._update_ui_state()

        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            self.current_editing_index = None
            self.inspector_group.reset_inspector()
            return

        item_id, dm = self._get_danmaku_for_row(selected_indexes[0].row())
        if item_id is None or dm is None:
            return

        self.current_editing_index = item_id
        self.inspector_group.load_danmaku(dm)

    def _apply_properties(self, new_props: dict[EditorField, Any]):
        """Inspector 回调：应用弹幕属性修改"""
        if self.current_editing_index is None or not self.session:
            return

        changed = self.session.update_item_properties(self.current_editing_index, new_props)
        if changed:
            # 记录当前选中的行，刷新表格后恢复选中
            row = self.table.currentIndex().row()
            self._refresh_table()
            if 0 <= row < self.model.rowCount():
                self.table.selectRow(row)

    def open_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid() or not self.session:
            return

        menu = QMenu(self)
        edit_action = menu.addAction("✏️ 编辑内容")
        delete_action = menu.addAction("🗑️ 删除此条")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))

        item_id, _ = self._get_danmaku_for_row(index.row())
        if item_id is None:
            return

        if action == edit_action:
            self._edit_row(index.row())
        elif action == delete_action:
            self.session.delete_items([item_id])
            self._refresh_table()

    def on_table_double_click(self, index: QModelIndex):
        """双击编辑内容"""
        if index.column() == 3:
            self._edit_row(index.row())

    def _edit_row(self, row):
        if not self.session:
            return

        item_id, dm = self._get_danmaku_for_row(row)
        if item_id is None or dm is None:
            return

        current_text = dm.msg
        dialog = EditDanmakuDialog(current_text, self)
        if dialog.exec():
            new_text = dialog.get_text()
            if new_text and new_text != current_text:
                self.session.update_item_content(item_id, new_text)
                self._refresh_table()
                self.table.selectRow(row)  # 恢复选中状态
            elif not new_text:
                reply = QMessageBox.question(self, "确认删除", "内容为空，是否直接删除该条弹幕？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    self.session.delete_items([item_id])
                    self._refresh_table()

    def delete_selected_items(self):
        """批量删除选中项"""
        if not self.session:
            return

        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            return

        # 收集所有的 UUID
        uids = [
            uid for row_idx in selected_indexes
            if (uid := self.model.get_item_id(row_idx.row())) is not None
        ]

        if uids:
            self.session.delete_items(uids)
            self._refresh_table()

    def undo(self):
        """撤销"""
        if not self.session:
            return

        if self.session.undo():
            self._refresh_table()

    def batch_remove_newlines(self):
        if not self.session:
            return

        mod, dele = self.session.batch_remove_newlines()
        self._show_batch_result(mod, dele)

    def batch_truncate_length(self):
        if not self.session:
            return

        count = self.session.batch_truncate_length()
        if count > 0:
            self._refresh_table()
            QMessageBox.information(self, "处理完成", f"已截断 {count} 条过长弹幕。")
        else:
            QMessageBox.information(self, "无变化", "未发现过长弹幕。")

    def _show_batch_result(self, mod, dele):
        if mod > 0 or dele > 0:
            self._refresh_table()
            QMessageBox.information(self, "处理完成", f"修复: {mod} 条\n删除: {dele} 条")
        else:
            QMessageBox.information(self, "无变化", "未发现相关问题。")

    def apply_changes(self):
        """应用修改"""
        if not self.session:
            return

        self.current_editing_index = None
        self.inspector_group.reset_inspector()

        total, fixed, deleted = self.session.commit_to_state()

        self.logger.info(f"修改已应用: 修复 {fixed}, 删除 {deleted}")
        QMessageBox.information(
            self,
            "应用成功",
            f"发送队列已更新！\n\n修复: {fixed} 条\n移除: {deleted} 条\n剩余总数: {total} 条"
        )

        self._refresh_table()
        self.status_label.setText("修改已应用。")
        self.status_label.setStyleSheet("color: green;")
        self._update_ui_state()

    def open_offset_dialog(self):
        if not self.session or not self.session.has_active_session:
            return

        dlg = TimeOffsetDialog(self)
        if dlg.exec():
            offset_ms = dlg.get_offset_ms()
            if offset_ms != 0:
                count = self.session.shift_time_axis(offset_ms)
                self._refresh_table()
                if count > 0:
                    self.logger.info(f"成功平移了 {count} 条弹幕的时间轴。")
                else:
                    self.logger.info("平移操作未导致任何数据变化。")

    # --- Qt Methods ---
    def showEvent(self, event):
        super().showEvent(event)
        self._update_ui_state()