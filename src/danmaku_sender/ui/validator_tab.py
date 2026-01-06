import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QMenu, QInputDialog
)
from PySide6.QtCore import Qt

from ..core.validator_session import ValidatorSession
from ..core.bili_danmaku_utils import format_ms_to_hhmmss


class ValidatorTab(QWidget):
    def __init__(self):
        super().__init__()
        self._state = None
        self.session = None
        self.logger = None

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
        self.run_btn.clicked.connect(self.run_validation)

        # 批量处理按钮
        self.batch_btn = QPushButton("批量修复")
        self.batch_btn.setFixedWidth(100)
        self.batch_btn.setEnabled(False)

        # 创建下拉菜单
        self.batch_menu = QMenu(self)
        self.batch_menu.addAction("一键去除所有换行符", self.batch_remove_newlines)
        self.batch_menu.addAction("一键截断过长弹幕(>100字)", self.batch_truncate_length)
        self.batch_btn.setMenu(self.batch_menu)

        self.undo_btn = QPushButton("撤销")
        self.undo_btn.setFixedWidth(80)
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self.undo)

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
        self.table.setHorizontalHeaderLabels(["序号", "时间", "问题描述", "弹幕内容 (双击编辑)"])

        # 设置表格行为
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemDoubleClicked.connect(self.on_table_double_click)

        # 右键菜单
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_context_menu)

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
        self.delete_btn.clicked.connect(self.delete_selected_items)

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
        bottom_layout.addWidget(self.apply_btn)

        main_layout.addLayout(bottom_layout)
        self.setLayout(main_layout)

    def bind_state(self, state):
        self._state = state
        self.session = ValidatorSession(state)
        self.logger = logging.getLogger("ValidatorTab")

    def run_validation(self):
        """运行验证逻辑"""
        if not self._state:
            return
        
        # 校验前置条件
        if not self._state.video_state.loaded_danmakus:
            QMessageBox.warning(self, "无法验证", "请先在 “发射器” 页面加载弹幕文件。")
            return
        
        if not self._state.video_state.selected_cid:
            QMessageBox.warning(self, "无法验证", "请先在 “发射器” 页面选择一个分P（用于检查时间戳）。")
            return

        # 检查未保存修改
        if self.session.is_dirty:
            reply = QMessageBox.question(self, "确认", "当前有未应用的修改，重新验证将丢弃这些修改。\n是否继续？", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return
            
        # 执行验证
        self.status_label.setText("正在验证...")
        self.status_label.setStyleSheet("color: blue;")
        
        has_issues = self.session.load_and_validate()
        self._refresh_table()
        
        if not has_issues:
            self.status_label.setText("✅ 验证通过: 所有弹幕均符合规范！")
            self.status_label.setStyleSheet("color: green;")
            QMessageBox.information(self, "验证通过", "所有弹幕均符合规范！")
            self._set_buttons_enabled(False)
        else:
            count = len(self.session.current_issues)
            self.status_label.setText(f"❌ 发现 {count} 条问题弹幕，请处理。")
            self.status_label.setStyleSheet("color: red;")
            self._set_buttons_enabled(True)

    def _refresh_table(self):
        """刷新表格"""
        self.table.setRowCount(0)
        items = self.session.get_display_items()

        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            idx_item = QTableWidgetItem(str(item['original_index'] + 1))
            idx_item.setData(Qt.UserRole, item['original_index'])
            
            time_str = format_ms_to_hhmmss(item['time_ms'])
            
            self.table.setItem(row, 0, idx_item)
            self.table.setItem(row, 1, QTableWidgetItem(time_str))
            self.table.setItem(row, 2, QTableWidgetItem(item['reason']))
            self.table.setItem(row, 3, QTableWidgetItem(item['current_content']))

        # 更新按钮状态
        self.undo_btn.setEnabled(self.session.can_undo)
        if self.session.is_dirty:
            self.status_label.setText("⚠️ 有未应用的修改！请点击“应用所有修改”按钮。")
            self.status_label.setStyleSheet("color: #d35400;") # 橙色
            self.apply_btn.setEnabled(True)
        elif self.session.has_active_session and self.table.rowCount() == 0:
            self.status_label.setText("所有问题已处理，请点击应用。")
            self.apply_btn.setEnabled(True)

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
            original_index = self.table.item(item.row(), 0).data(Qt.UserRole)
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
        
        original_index = idx_item.data(Qt.UserRole)
        current_text = self.table.item(row, 3).text()

        new_text, ok = QInputDialog.getText(self, "编辑弹幕", "请输入修改后的内容：", text=current_text)

        if ok:
            clean_text = new_text.strip()
            if clean_text:
                if clean_text != current_text:
                    self.session.update_item_content(original_index, clean_text)
                    self._refresh_table()
            else:
                reply = QMessageBox.question(self, "确认删除", "内容为空，是否直接删除该条弹幕？", QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    self.session.delete_item(original_index)
                    self._refresh_table()

    def delete_selected_items(self):
        """删除选中项"""
        rows = set()
        for item in self.table.selectedItems():
            rows.add(item.row())
        
        if not rows:
            return

        for row in rows:
            original_index = self.table.item(row, 0).data(Qt.UserRole)
            self.session.delete_item(original_index)

        self._refresh_table()

    def undo(self):
        """撤销"""
        if self.session.undo():
            self._refresh_table()

    def batch_remove_newlines(self):
        mod, dele = self.session.batch_remove_newlines()
        self._show_batch_result(mod, dele)

    def batch_truncate_length(self):
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
        total, fixed, deleted = self.session.apply_changes()
        
        self.logger.info(f"修改已应用: 修复 {fixed}, 删除 {deleted}")
        QMessageBox.information(self, "应用成功", 
                                f"发送队列已更新！\n\n修复: {fixed} 条\n移除: {deleted} 条\n剩余总数: {total} 条")
        
        self._refresh_table()
        self.status_label.setText("修改已应用。")
        self.status_label.setStyleSheet("color: green;")
        self._set_buttons_enabled(False)
        self.apply_btn.setEnabled(False)

    def _set_buttons_enabled(self, enabled):
        self.batch_btn.setEnabled(enabled)
        self.delete_btn.setEnabled(enabled)