import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QMenu, QLineEdit, QFrame, QCheckBox, QGroupBox
)

from .dialogs import EditDanmakuDialog, TimeOffsetDialog

from ..core.state import AppState
from ..core.editor_session import EditorSession
from ..utils.time_utils import format_ms_to_hhmmss


class EditorTab(QWidget):
    def __init__(self):
        super().__init__()
        self._state: AppState | None = None
        self.session: EditorSession | None = None
        self.logger = logging.getLogger("EditorTab")

        self._create_ui()

        self._update_ui_state()

    def _create_ui(self):
        # 主布局
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- 规则管理区 ---
        config_group = QGroupBox("校验与过滤规则")
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

        # --- 中间表格区 ---
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["序号", "时间", "问题描述", "弹幕内容 (双击编辑)"])

        # 设置表格行为
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(self.on_table_double_click)
        self.table.itemSelectionChanged.connect(self._update_ui_state)

        # 右键菜单
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_context_menu)

        # 设置列宽调整模式
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        main_layout.addWidget(self.table)

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
        idx_item = self.table.item(row, 0)
        if not idx_item:
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