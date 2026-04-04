import logging
from typing import Any

from PySide6.QtCore import Qt, QModelIndex
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableView, QHeaderView, QAbstractItemView, QMessageBox,
    QMenu, QFrame, QCheckBox, QSplitter
)

from .components import EditorTableModel, ValidationRulesGroup, PropertyInspectorGroup
from .dialogs import EditDanmakuDialog, TimeOffsetDialog

from ...core.engines.editor_session import EditorSession, EditorField, InsertPosition
from ...core.entities.danmaku import Danmaku
from ...core.state import AppState
from ...utils.resource_utils import get_svg_icon


class EditorPage(QWidget):
    def __init__(self):
        super().__init__()
        self._state: AppState | None = None
        self.session: EditorSession | None = None
        self.logger = logging.getLogger("App.System.UI.Editor")

        self.current_item_id: str | None = None

        self._create_ui()

    def _create_ui(self):
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- 顶部工具栏 ---
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(8)

        # A: 文件级操作 (预留)
        self.btn_new = QPushButton(get_svg_icon("note_add.svg"), "新建")
        self.btn_new.setEnabled(False)
        self.btn_new.setToolTip("预留功能：新建空白弹幕文件")

        self.btn_import = QPushButton(get_svg_icon("file_open.svg"), "导入 XML")
        self.btn_import.setEnabled(False)
        self.btn_import.setToolTip("预留功能：从本地导入外部 XML 文件")

        self.btn_export = QPushButton(get_svg_icon("file_save.svg"), "导出为 XML")
        self.btn_export.setEnabled(False)
        self.btn_export.setToolTip("预留功能：将当前工作区内容导出")

        toolbar_layout.addWidget(self.btn_new)
        toolbar_layout.addWidget(self.btn_import)
        toolbar_layout.addWidget(self.btn_export)

        v_line1 = QFrame()
        v_line1.setFrameShape(QFrame.Shape.VLine)
        v_line1.setFrameShadow(QFrame.Shadow.Sunken)
        toolbar_layout.addWidget(v_line1)

        # B: 批量处理工具 (下拉菜单)
        self.btn_batch = QPushButton(get_svg_icon("handyman.svg"), "批量处理")
        self.btn_batch.setEnabled(False)

        self.batch_menu = QMenu(self)
        self.batch_menu.addAction(get_svg_icon("format_clear.svg"), "一键去除所有换行符", self.batch_remove_newlines)
        self.batch_menu.addAction(get_svg_icon("short_text.svg"), "一键截断过长弹幕(>100字)", self.batch_truncate_length)
        self.batch_menu.addAction(get_svg_icon("sync_alt.svg"), "整体平移时间轴", self.open_offset_dialog)
        self.btn_batch.setMenu(self.batch_menu)

        toolbar_layout.addWidget(self.btn_batch)
        toolbar_layout.addStretch()

        # C: 核心工作流
        self.undo_btn = QPushButton(get_svg_icon("undo.svg"), "撤销")
        self.undo_btn.setFixedWidth(80)
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self.undo)

        self.run_btn = QPushButton(get_svg_icon("play_arrow.svg"), "开始校验")
        self.run_btn.setStyleSheet("background-color: #3498db; color: white; font-weight: bold;")
        self.run_btn.setFixedWidth(100)
        self.run_btn.clicked.connect(self.run_validation)

        # 预览切换
        self.preview_mode_cb = QCheckBox("预览模式(全量显示)")
        self.preview_mode_cb.setToolTip("开启后显示所有弹幕，正常的弹幕将以灰色显示。")
        self.preview_mode_cb.stateChanged.connect(self._refresh_table)

        v_line2 = QFrame()
        v_line2.setFrameShape(QFrame.Shape.VLine)
        v_line2.setFrameShadow(QFrame.Shadow.Sunken)

        toolbar_layout.addWidget(self.undo_btn)
        toolbar_layout.addWidget(self.run_btn)
        toolbar_layout.addSpacing(10)
        toolbar_layout.addWidget(v_line2)
        toolbar_layout.addSpacing(10)
        toolbar_layout.addWidget(self.preview_mode_cb)

        main_layout.addLayout(toolbar_layout)

        # --- 规则管理区 ---
        self.rules_group = ValidationRulesGroup()
        main_layout.addWidget(self.rules_group)

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

        self.status_label = QLabel("提示: 请先在“发射器”页面加载文件并选择分P。")
        self.status_label.setStyleSheet("color: #7f8c8d;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.apply_btn = QPushButton(get_svg_icon("done_all.svg"), "应用所有修改")
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

        bottom_layout.addWidget(self.status_label, stretch=1)
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
            self.logger.warning(f"UI 状态不同步: 在 Session 中找不到 UUID 为 {item_id} 的弹幕。")
            return None, None

        return item_id, item.working

    def _update_ui_state(self):
        """统一状态机控制"""
        if not self.session or not self._state:
            for btn in [self.run_btn, self.btn_batch, self.undo_btn, self.apply_btn]:
                btn.setEnabled(False)
            self.status_label.setText("提示: 请先在“发射器”页面加载文件并选择分P。")
            self.status_label.setStyleSheet("color: #7f8c8d;")
            return

        video_state = self._state.video_state
        session = self.session
        has_items = self.model.rowCount() > 0

        self.run_btn.setEnabled(bool(video_state.loaded_danmakus) and video_state.selected_cid is not None)
        self.btn_batch.setEnabled(session.has_active_session and has_items)
        self.undo_btn.setEnabled(session.can_undo)
        self.apply_btn.setEnabled(session.is_dirty)

        if session.is_dirty:
            self.status_label.setText("⚠️ 有未应用的修改！请点击“应用所有修改”按钮。")
            self.status_label.setStyleSheet("color: #d35400;")
        elif session.has_active_session:
            count = session.active_error_count
            if count > 0:
                self.status_label.setText(f"❌ 发现 {count} 条问题弹幕，请处理。")
                self.status_label.setStyleSheet("color: red;")
            else:
                self.status_label.setText("✅ 验证通过，当前无问题。")
                self.status_label.setStyleSheet("color: green;")
        else:
            self.status_label.setText("提示: 点击“开始校验”以检查弹幕合法性。")
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

        self.current_item_id = None
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
            self.current_item_id = None
            self.inspector_group.reset_inspector()
            return

        item_id, dm = self._get_danmaku_for_row(selected_indexes[0].row())
        if item_id is None or dm is None:
            return

        self.current_item_id = item_id
        self.inspector_group.load_danmaku(dm)

    def _apply_properties(self, new_props: dict[EditorField, Any]):
        """Inspector 回调：应用弹幕属性修改"""
        if self.current_item_id is None or not self.session:
            return

        changed = self.session.update_item_properties(self.current_item_id, new_props)
        if changed:
            # 记录当前选中的行，刷新表格后恢复选中
            row = self.table.currentIndex().row()
            self._refresh_table()
            if 0 <= row < self.model.rowCount():
                self.table.selectRow(row)

    def on_table_double_click(self, index: QModelIndex):
        """双击编辑内容"""
        if index.column() == 3:
            self._edit_row(index.row())

    def open_context_menu(self, pos):
        """打开表格右键上下文菜单"""
        index = self.table.indexAt(pos)
        if not index.isValid() or not self.session:
            return

        menu = QMenu(self)

        edit_action = menu.addAction(get_svg_icon("edit.svg"), "编辑内容")
        menu.addSeparator()

        insert_above_action = menu.addAction(get_svg_icon("vertical_align_top.svg"), "在上方插入新弹幕")
        insert_below_action = menu.addAction(get_svg_icon("vertical_align_bottom.svg"), "在下方插入新弹幕")

        menu.addSeparator()

        delete_action = menu.addAction(get_svg_icon("delete.svg"), "删除选中条目")

        # 弹出菜单
        action = menu.exec(self.table.viewport().mapToGlobal(pos))

        if action == edit_action:
            self._edit_row(index.row())
        elif action == insert_above_action:
            self._insert_row(index.row(), InsertPosition.ABOVE)
        elif action == insert_below_action:
            self._insert_row(index.row(), InsertPosition.BELOW)
        elif action == delete_action:
            self.delete_selected_items()

    def _edit_row(self, row):
        if not self.session:
            return

        item_id, dm = self._get_danmaku_for_row(row)
        if item_id is None or dm is None:
            return

        dialog = EditDanmakuDialog(dm, self)
        if dialog.exec():
            new_props = dialog.get_properties()
            if not new_props[EditorField.MSG]:
                if QMessageBox.question(self, "确认删除", "内容为空，是否直接删除该条弹幕？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                    self.session.delete_items([item_id])
                    self._refresh_table()
            else:
                if self.session.update_item_properties(item_id, new_props):
                    self._refresh_table()
                    self.table.selectRow(row)

    def _insert_row(self, row: int, position: InsertPosition):
        """插入新弹幕"""
        if not self.session:
            return

        item_id, _ = self._get_danmaku_for_row(row)
        if not item_id:
            return

        new_uid = self.session.insert_item(item_id, position)
        if new_uid:
            self._refresh_table()
            # 定位到新插入的行
            for i in range(self.model.rowCount()):
                if self.model.get_item_id(i) == new_uid:
                    self.table.selectRow(i)
                    self._edit_row(i)
                    break

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

        self.current_item_id = None
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