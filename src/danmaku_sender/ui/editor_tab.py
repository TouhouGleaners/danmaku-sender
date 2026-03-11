import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QMenu, QLineEdit, QFrame, QCheckBox, QGroupBox, QSizePolicy,
    QSplitter, QFormLayout, QDoubleSpinBox, QComboBox, QSpinBox, QTextEdit, QColorDialog
)

from .dialogs import EditDanmakuDialog, TimeOffsetDialog

from ..core.editor_session import EditorSession, EditorField
from ..core.models.danmaku import Danmaku
from ..core.state import AppState
from ..utils.time_utils import format_ms_to_hhmmss


class EditorTab(QWidget):
    def __init__(self):
        super().__init__()
        self._state: AppState | None = None
        self.session: EditorSession | None = None
        self.logger = logging.getLogger("EditorTab")

        self.current_editing_index: int | None = None

        self._create_ui()

        self._update_ui_state()

    def _create_ui(self):
        # 主布局
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- 规则管理区 ---
        config_group = QGroupBox("校验与过滤规则")
        config_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        config_layout = QVBoxLayout()
        config_layout.setSpacing(8)

        self.sys_info = QLabel("系统规则: 限制长度(≤100字)、禁止换行、拦截特殊符号 (已默认开启)")
        self.sys_info.setStyleSheet("color: #95a5a6; font-size: 11px;")
        config_layout.addWidget(self.sys_info)

        keyword_layout = QHBoxLayout()
        self.enable_custom_checkbox = QCheckBox("关键词拦截:")
        self.enable_custom_checkbox.setToolTip("开启后将拦截包含以下关键词的弹幕")
        keyword_layout.addWidget(self.enable_custom_checkbox)

        self.keywords_input = QLineEdit()
        self.keywords_input.setPlaceholderText("用中文或英文逗号分隔，如：应用, 过滤")
        self.keywords_input.setStyleSheet("padding: 2px 5px;")
        keyword_layout.addWidget(self.keywords_input, stretch=1)

        config_layout.addLayout(keyword_layout)
        config_group.setLayout(config_layout)
        main_layout.addWidget(config_group)

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
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["序号", "时间", "问题描述", "弹幕内容"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(self.on_table_double_click)
        
        # 将表格选择变更连接到右侧属性面板
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_context_menu)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        self.splitter.addWidget(self.table)

        # --- 右侧：属性检查器面板 ---
        self.prop_group = QGroupBox("属性检查器")
        self.prop_group.setEnabled(False)  # 初始未选中，禁用
        prop_layout = QVBoxLayout()
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
        self.prop_save_btn.clicked.connect(self._apply_properties)
        prop_layout.addWidget(self.prop_save_btn)

        self.prop_group.setLayout(prop_layout)
        self.splitter.addWidget(self.prop_group)

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
        self.setLayout(main_layout)

    # --- 色彩转换工具 ---
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
        bili_colors =[
            "#FE0302", "#FF7204", "#FFAA02", "#FFD302", "#FFFF00", "#A0EE00", "#00CD00",
            "#019899", "#4266BE", "#89D5FF", "#CC0273", "#222222", "#9B9B9B", "#FFFFFF"
        ]

        # 注入到 QColorDialog 的系统自定义颜色插槽中
        for i, hex_color in enumerate(bili_colors):
            QColorDialog.setCustomColor(i, QColor(hex_color))

        dialog = QColorDialog(self)
        dialog.setWindowTitle("选择弹幕颜色 (左下角为B站标准色)")
        dialog.setCurrentColor(QColor(self.int_to_hex(self.current_color_val)))

        if dialog.exec() == QColorDialog.DialogCode.Accepted:
            color = dialog.currentColor()
            hex_str = color.name()
            self.current_color_val = self.hex_to_int(hex_str)
            self._update_color_btn_style(hex_str)

    def _populate_font_sizes(self, custom_size: int | None = None):
        """统一填充字号选项"""
        STANDARD_FONT_SIZES = {
            "标准 (25)": 25,
            "小 (18)": 18,
            "大 (36)": 36
        }
        self.prop_fontsize.blockSignals(True)
        self.prop_fontsize.clear()
        for text, value in STANDARD_FONT_SIZES.items():
            self.prop_fontsize.addItem(text, value)
        
        # 如果是解析出的非常规字号，添加自定义选项
        if custom_size and custom_size not in STANDARD_FONT_SIZES.values():
            self.prop_fontsize.addItem(f"自定义 ({custom_size})", custom_size)
            self.prop_fontsize.setCurrentIndex(self.prop_fontsize.count() - 1)
        else:
            # 默认选标准
            idx = self.prop_fontsize.findData(25)
            self.prop_fontsize.setCurrentIndex(idx if idx >= 0 else 0)
        self.prop_fontsize.blockSignals(False)

    def _reset_inspector(self):
        """彻底重置属性面板状态，防止指向失效的 Session 数据"""
        self.current_editing_index = None
        self.prop_group.setEnabled(False)
        self.prop_text.clear()
        
        self.prop_time.blockSignals(True)
        self.prop_time.setValue(0.0)
        self.prop_time.blockSignals(False)
        
        self.prop_mode.setCurrentIndex(0)
        self._populate_font_sizes()
        
        self.current_color_val = 16777215
        self._update_color_btn_style("#ffffff")
        self.logger.debug("Inspector has been explicitly reset.")

    # --- 交互核心逻辑 ---
    def _on_selection_changed(self):
        """当表格选中项变化时，同步更新 UI 状态并渲染属性面板"""
        self._update_ui_state()

        selected = self.table.selectedItems()
        if not selected or not self.session:
            self._reset_inspector()
            return
            
        # 仅取选中的第一行展示在属性面板中
        row = selected[0].row()
        idx_item = self.table.item(row, 0)
        if not idx_item:
            return
            
        original_index = idx_item.data(Qt.ItemDataRole.UserRole)
        self.current_editing_index = original_index
        
        # 取出对象并赋值
        dm: Danmaku = self.session.staged_danmakus[original_index]
        
        self.prop_time.blockSignals(True)
        self.prop_time.setValue(dm.progress / 1000.0)
        self.prop_time.blockSignals(False)
        
        mode_idx = self.prop_mode.findData(dm.mode)
        self.prop_mode.setCurrentIndex(mode_idx if mode_idx >= 0 else 1)
            
        self._populate_font_sizes(dm.fontsize)
        
        self.current_color_val = dm.color
        self._update_color_btn_style(self.int_to_hex(dm.color))
        
        self.prop_text.setPlainText(dm.msg)
        self.prop_group.setEnabled(True)

    def _apply_properties(self):
        """应用弹幕属性修改"""
        if self.current_editing_index is None or not self.session:
            return
            
        clean_text = self.prop_text.toPlainText().replace('\n', '').replace('\r', '').strip()
        if not clean_text:
            QMessageBox.warning(self, "错误", "弹幕内容不能为空！如需删除请点击下方的删除按钮。")
            return

        new_props = {
            EditorField.PROGRESS: int(self.prop_time.value() * 1000),
            EditorField.MODE: self.prop_mode.currentData(),
            EditorField.FONT_SIZE: self.prop_fontsize.currentData(),
            EditorField.COLOR: self.current_color_val,
            EditorField.MSG: clean_text
        }
        
        changed = self.session.update_item_properties(self.current_editing_index, new_props)
        if changed:
            # 记录当前选中的行，刷新表格后恢复选中
            row = self.table.currentRow()
            self._refresh_table()
            if 0 <= row < self.table.rowCount():
                self.table.selectRow(row)

    # --- Qt Methods ---
    def showEvent(self, event):
        super().showEvent(event)
        self._update_ui_state()

    def bind_state(self, state: AppState):
        if self._state is state:
            return

        if self._state is not None:
            self._disconnect_signals()

        self._state = state
        self.session = EditorSession(state)

        validation_cfg = state.validation_config

        # 初始化 UI 值
        self.enable_custom_checkbox.blockSignals(True)
        self.enable_custom_checkbox.setChecked(validation_cfg.enabled)
        self.enable_custom_checkbox.blockSignals(False)

        self.keywords_input.blockSignals(True)
        self.keywords_input.setText(", ".join(validation_cfg.blocked_keywords))
        self.keywords_input.blockSignals(False)

        self.keywords_input.setEnabled(validation_cfg.enabled)

        # 重新连接信号
        self.enable_custom_checkbox.stateChanged.connect(self._on_toggle_custom)
        self.keywords_input.textChanged.connect(self._on_keywords_changed)

        self._update_ui_state()

    def _disconnect_signals(self):
        """安全断开所有已绑定的信号"""
        try:
            self.enable_custom_checkbox.stateChanged.disconnect()
        except (RuntimeError, TypeError):
            pass

        try:
            self.keywords_input.textChanged.disconnect()
        except (RuntimeError, TypeError):
            pass

    def _on_toggle_custom(self):
        """处理总开关切换"""
        if not self._state:
            return

        is_on = self.enable_custom_checkbox.isChecked()
        self._state.validation_config.enabled = is_on
        self.keywords_input.setEnabled(is_on)

    def _on_keywords_changed(self, text):
        """处理关键词文本变更"""
        if not self._state:
            return

        raw_text = text.replace('，', ',').lower()
        parts = [k.strip() for k in raw_text.split(',') if k.strip()]
        unique_keywords = sorted(list(set(parts)))

        self._state.validation_config.blocked_keywords = unique_keywords

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
        has_items = self.table.rowCount() > 0

        self.offset_btn.setEnabled(session_active)
        self.batch_btn.setEnabled(session_active and has_items)
        self.delete_btn.setEnabled(session_active and len(self.table.selectedItems()) > 0)

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
        
        self._reset_inspector()
        has_issues = self.session.checkout_from_state()

        if not has_issues:
            QMessageBox.information(self, "验证通过", "所有弹幕均符合规范！")

        self._refresh_table()

    def _refresh_table(self):
        """刷新表格"""
        if not self.session:
            return

        self.table.setRowCount(0)
        items = self.session.generate_view_model(show_all=self.preview_mode_cb.isChecked())

        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            idx_item = QTableWidgetItem(str(item['source_index'] + 1))
            idx_item.setData(Qt.ItemDataRole.UserRole, item['source_index'])
            
            time_item = QTableWidgetItem(format_ms_to_hhmmss(item['time_ms']))
            reason_item = QTableWidgetItem(item['error_msg'])
            content_item = QTableWidgetItem(item['content'])

            if item['is_valid']:
                # 正常行：文字变灰
                gray_brush = QBrush(QColor("#95a5a6"))
                for it in [idx_item, time_item, reason_item, content_item]:
                    it.setForeground(gray_brush)
            else:
                # 异常行：理由变红，背景淡红
                error_bg = QColor("#fff2f2")
                reason_item.setForeground(QColor("#e74c3c"))
                for it in [idx_item, time_item, reason_item, content_item]:
                    it.setBackground(error_bg)

            self.table.setItem(row, 0, idx_item)
            self.table.setItem(row, 1, time_item)
            self.table.setItem(row, 2, reason_item)
            self.table.setItem(row, 3, content_item)

        self._update_ui_state()

    def open_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return

        if not self.session:
            return

        menu = QMenu(self)
        edit_action = menu.addAction("✏️ 编辑内容")
        delete_action = menu.addAction("🗑️ 删除此条")

        # 在鼠标位置弹出
        action = menu.exec(self.table.mapToGlobal(pos))

        if action == edit_action:
            self._edit_row(item.row())
        elif action == delete_action:
            # 获取原始索引并删除
            original_index = self.table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
            self.session.delete_item(original_index)
            self._refresh_table()

    def on_table_double_click(self, item):
        """双击编辑内容"""
        if item.column() == 3:
            self._edit_row(item.row())

    def _edit_row(self, row):
        """兼容原有的双击弹窗功能（与侧边栏属性检查器双线并行）"""
        idx_item = self.table.item(row, 0)
        if not idx_item:
            return

        if not self.session:
            return

        original_index = idx_item.data(Qt.ItemDataRole.UserRole)
        current_text = self.table.item(row, 3).text()

        dialog = EditDanmakuDialog(current_text, self)
        if dialog.exec():
            new_text = dialog.get_text()
            if new_text:
                if new_text != current_text:
                    self.session.update_item_content(original_index, new_text)
                    self._refresh_table()
                    # 重新触发侧边栏更新
                    if self.current_editing_index == original_index:
                        self.table.selectRow(row)
            else:
                reply = QMessageBox.question(self, "确认删除", "内容为空，是否直接删除该条弹幕？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    self.session.delete_item(original_index)
                    self._refresh_table()

    def delete_selected_items(self):
        """删除选中项"""
        if not self.session:
            return
        
        rows = set()
        for item in self.table.selectedItems():
            rows.add(item.row())
        
        if not rows:
            return

        for row in rows:
            original_index = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            self.session.delete_item(original_index)

        self._refresh_table()

    def undo(self):
        """撤销"""
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
        
        self._reset_inspector()
        
        total, fixed, deleted = self.session.commit_to_state()
        
        self.logger.info(f"修改已应用: 修复 {fixed}, 删除 {deleted}")
        QMessageBox.information(self, "应用成功", 
                                f"发送队列已更新！\n\n修复: {fixed} 条\n移除: {deleted} 条\n剩余总数: {total} 条")
        
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