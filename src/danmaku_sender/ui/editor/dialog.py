import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QModelIndex, QPoint, Slot
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableView, QHeaderView, QAbstractItemView, QMessageBox,
    QMenu, QFrame, QCheckBox, QSplitter, QFileDialog
)

from .components import EditorTableModel, ValidationRulesGroup, PropertyInspectorGroup
from .dialogs import EditDanmakuDialog, TimeOffsetDialog, ArrayGeneratorDialog

from danmaku_sender.ui.framework.style_loader import SvgIcon
from danmaku_sender.controller.editor_controller import EditorController
from danmaku_sender.types.models.editor_types import EditorField, InsertPosition
from danmaku_sender.types.models.queue import QueueTask
from danmaku_sender.runtime.state.app_state import AppState


class EditorDialog(QDialog):
    """编辑器弹窗 - 用于编辑单个任务的弹幕数据"""

    def __init__(self, task: QueueTask, state: AppState, parent=None):
        super().__init__(parent)
        self.task = task
        self.controller = EditorController(task, state, self)
        self.logger = logging.getLogger(__name__)

        self.current_item_id: str | None = None

        self.setWindowTitle(f"编辑弹幕 — {task.target.display_string}")
        self.setMinimumSize(900, 600)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )

        self._create_ui()
        self.controller.dataChanged.connect(self._refresh_table)

        # 加载任务的弹幕数据
        self._load_task_danmakus()

    def _load_task_danmakus(self):
        """加载任务的弹幕数据到编辑器"""
        if self.controller.load_from_task():
            self._refresh_table()

    # region UI Setup & Data Binding
    def _create_ui(self):
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- 顶部工具栏 ---
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(8)

        # A: 文件级操作
        self.btn_import = QPushButton(SvgIcon("file_open.svg"), "导入 XML")
        self.btn_import.clicked.connect(self._import_xml)

        self.btn_export = QPushButton(SvgIcon("file_save.svg"), "导出为 XML")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export_xml)

        toolbar_layout.addWidget(self.btn_import)
        toolbar_layout.addWidget(self.btn_export)

        v_line1 = QFrame()
        v_line1.setFrameShape(QFrame.Shape.VLine)
        v_line1.setFrameShadow(QFrame.Shadow.Sunken)
        toolbar_layout.addWidget(v_line1)

        # B: 批量处理工具 (下拉菜单)
        self.btn_batch = QPushButton(SvgIcon("handyman.svg"), "批量处理")
        self.btn_batch.setEnabled(False)

        self.batch_menu = QMenu(self)
        self.batch_menu.addAction(SvgIcon("format_clear.svg"), "一键去除所有换行符", self._batch_remove_newlines)
        self.batch_menu.addAction(SvgIcon("short_text.svg"), "一键截断过长弹幕(>100字)", self._batch_truncate_length)
        self.batch_menu.addAction(SvgIcon("sync_alt.svg"), "整体平移时间轴", self._prompt_time_offset)
        self.btn_batch.setMenu(self.batch_menu)

        toolbar_layout.addWidget(self.btn_batch)
        toolbar_layout.addStretch()

        # C: 核心工作流
        self.undo_btn = QPushButton(SvgIcon("undo.svg"), "撤销")
        self.undo_btn.setFixedWidth(80)
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self._undo)

        self.run_btn = QPushButton(SvgIcon("play_arrow.svg"), "开始校验")
        self.run_btn.setStyleSheet("background-color: #3498db; color: white; font-weight: bold;")
        self.run_btn.setFixedWidth(100)
        self.run_btn.clicked.connect(self._run_validation)

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
        self.rules_group = ValidationRulesGroup(self.controller.state)
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
        self.table.doubleClicked.connect(self._on_table_double_click)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._open_context_menu)

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

        self.status_label = QLabel('提示: 请先在"发射器"页面加载文件并选择分P。')
        self.status_label.setStyleSheet("color: #7f8c8d;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.apply_btn = QPushButton(SvgIcon("done_all.svg"), "应用所有修改")
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
        self.apply_btn.clicked.connect(self._apply_changes)

        bottom_layout.addWidget(self.status_label, stretch=1)
        bottom_layout.addWidget(self.apply_btn)

        main_layout.addLayout(bottom_layout)

        self._update_ui_state()

    def init_bindings(self):
        """将 UI 控件与 AppState 进行双向绑定"""
        self.rules_group.init_bindings()
        self._update_ui_state()

    # endregion
    # region State & UI Refresh Updates

    def _update_ui_state(self):
        """统一状态机控制"""
        ctrl = self.controller

        self.btn_import.setEnabled(True)
        self.run_btn.setEnabled(ctrl.source_data_exists)
        self.btn_batch.setEnabled(ctrl.has_data)
        self.btn_export.setEnabled(ctrl.has_data)
        self.undo_btn.setEnabled(ctrl.can_undo)
        self.apply_btn.setEnabled(ctrl.is_dirty)

        # 更新状态提示文本和样式
        # 脏数据
        if ctrl.is_dirty:
            self.status_label.setText('⚠️ 有未保存的修改！请点击"保存到任务"按钮。')
            self.status_label.setStyleSheet("color: #d35400;")

        # 已校验数据
        elif ctrl.has_data:
            # 如果有错误，优先显示错误信息
            if ctrl.active_error_count > 0:
                self.status_label.setText(f"❌ 发现 {ctrl.active_error_count} 条问题弹幕，请处理。")
                self.status_label.setStyleSheet("color: red;")
            # 没有错误
            else:
                self.status_label.setText("✅ 验证通过，当前无问题。")
                self.status_label.setStyleSheet("color: green;")

        # 有源数据，待校验
        elif ctrl.source_data_exists:
            self.status_label.setText('提示: 点击"开始校验"以检查弹幕。')
            self.status_label.setStyleSheet("color: #7f8c8d;")

        # 未加载任何数据
        else:
            self.status_label.setText('提示: 请先在"发射器"页面加载文件，或点击新建。')
            self.status_label.setStyleSheet("color: #7f8c8d;")

    @Slot()
    def _refresh_table(self):
        """刷新表格"""
        view_items = self.controller.get_view_model(show_all=self.preview_mode_cb.isChecked())
        self.model.update_data(view_items)
        self._update_ui_state()

    @Slot()
    def _on_selection_changed(self):
        """表格选中行变化时，更新侧边栏检查器"""
        self._update_ui_state()

        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            self.current_item_id = None
            self.inspector_group.reset_inspector()
            return

        uid = self.model.get_item_id(selected_indexes[0].row())
        if uid:
            self.current_item_id = uid
            if dm := self.controller.get_item_danmaku(uid):
                self.inspector_group.load_danmaku(dm)

    # endregion
    # region Core Workflow (File & Validation)

    @Slot()
    def _import_xml(self):
        if self.controller.is_dirty:
            reply = QMessageBox.question(
                self, "放弃修改?",
                "当前有未应用的修改，导入新文件将覆盖并丢失这些数据。\n是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入弹幕 XML", "", "XML Files (*.xml);;All Files (*.*)"
        )

        if file_path:
            self.logger.info(f"📥 正在解析文件: {Path(file_path).name}")
            self.controller.import_xml_to_workspace(
                file_path,
                on_success=self._on_import_success,
                on_error=self._on_import_error,
            )

    @Slot(int)
    def _on_import_success(self, count: int):
        if count > 0:
            self.preview_mode_cb.setChecked(True)
            self.current_item_id = None
            self.inspector_group.reset_inspector()
        else:
            QMessageBox.warning(self, "导入失败", "未从文件中解析出有效的弹幕。")

    @Slot(str)
    def _on_import_error(self, err: str):
        self.logger.error(f"❌ 导入失败: {err}")
        QMessageBox.critical(self, "导入失败", f"解析 XML 时发生错误:\n{err}")

    @Slot()
    def _export_xml(self):
        """将当前工作区内容导出为 XML 文件"""
        # 提取当前工作区中，未被标记删除的所有弹幕
        working_dms = self.controller.get_working_danmakus()

        if not working_dms:
            QMessageBox.warning(self, "导出失败", "当前工作区没有任何可导出的弹幕。")
            return

        # 弹出保存文件对话框
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出弹幕为 XML",
            "exported_danmaku.xml",
            "XML Files (*.xml)"
        )

        if file_path:
            count = len(working_dms)
            self.controller.export_to_xml(
                working_dms, file_path,
                on_success=lambda _: self._on_export_success(count, file_path),
                on_error=self._on_export_error,
            )

    @Slot(int, str)
    def _on_export_success(self, count: int, file_path: str):
        QMessageBox.information(
            self,
            "导出成功",
            f"🎉 成功导出 {count} 条弹幕至：\n{file_path}"
        )

    @Slot(str)
    def _on_export_error(self, err: str):
        self.logger.error(f"❌ 导出失败: {err}")
        QMessageBox.critical(self, "导出失败", f"文件写入失败，请检查路径权限。\n错误信息:\n{err}")

    @Slot()
    def _run_validation(self):
        """运行验证逻辑"""
        # 校验前置条件
        if not self.controller.source_data_exists:
            QMessageBox.warning(self, "无法验证", "当前工作区为空，请先导入弹幕。")
            return

        # 检查未保存修改
        if self.controller.is_dirty:
            reply = QMessageBox.question(
                self,
                "确认",
                "当前有未保存的修改，重新验证将丢弃这些修改。\n是否继续？",
                buttons=QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.No:
                return

        # 执行验证
        self.status_label.setText("正在验证...")
        self.status_label.setStyleSheet("color: blue;")

        self.current_item_id = None
        self.inspector_group.reset_inspector()

        # 重新从任务加载弹幕数据并验证
        has_issues = self.controller.load_from_task()
        if not has_issues:
            QMessageBox.information(self, "验证通过", "所有弹幕均符合当前规范！")

    @Slot()
    def _apply_changes(self):
        """保存修改到任务"""
        self.current_item_id = None
        self.inspector_group.reset_inspector()

        # 获取编辑后的弹幕数据
        final_list = self.controller.get_working_danmakus()

        # 更新任务的弹幕数据
        self.task.danmakus = final_list
        self.task.total = len(final_list)

        self.logger.info(f"已保存 {len(final_list)} 条弹幕到任务")
        QMessageBox.information(
            self,
            "保存成功",
            f"已保存 {len(final_list)} 条弹幕到任务！"
        )

        self.accept()

    # endregion
    # region Item Operations (Row Level & Dialogs)

    def _select_row_by_uid(self, uid: str) -> int:
        """根据 UUID 定位并选中表格行"""
        for i in range(self.model.rowCount()):
            if self.model.get_item_id(i) == uid:
                self.table.selectRow(i)
                return i
        return -1

    def _apply_properties(self, new_props: dict[EditorField, Any]):
        """Inspector 回调：应用弹幕属性修改"""
        if not self.current_item_id:
            return

        if not self.controller.update_properties(self.current_item_id, new_props):
            return

        self._select_row_by_uid(self.current_item_id)

    @Slot(QPoint)
    def _open_context_menu(self, pos: QPoint):
        """打开表格右键上下文菜单"""
        index = self.table.indexAt(pos)
        if not index.isValid():
            return

        menu = QMenu(self)
        row = index.row()

        menu.addAction(SvgIcon("edit_document.svg"), "编辑内容", lambda: self._edit_row(row))
        menu.addSeparator()
        menu.addAction(SvgIcon("vertical_align_top.svg"), "在上方插入新弹幕", lambda: self._insert_row(row, InsertPosition.ABOVE))
        menu.addAction(SvgIcon("vertical_align_bottom.svg"), "在下方插入新弹幕", lambda: self._insert_row(row, InsertPosition.BELOW))
        menu.addSeparator()
        menu.addAction(SvgIcon("sync_alt.svg"), "平移选中弹幕的时间轴", self._shift_selected_items_time)
        adv_menu = menu.addMenu(SvgIcon("auto_awesome.svg"), "高级生成工具")
        adv_menu.addAction(SvgIcon("gradient.svg"), "生成彩虹弹幕阵列", lambda: self._generate_array(row))
        menu.addAction(SvgIcon("delete.svg"), "删除选中条目", self._delete_selected_items)

        # 弹出菜单
        menu.exec(self.table.viewport().mapToGlobal(pos))

    @Slot(QModelIndex)
    def _on_table_double_click(self, index: QModelIndex):
        """双击编辑内容"""
        if index.column() == 3:
            self._edit_row(index.row())

    def _edit_row(self, row):
        uid = self.model.get_item_id(row)
        if not uid:
            return

        dm = self.controller.get_item_danmaku(uid)
        if not dm:
            return

        dialog = EditDanmakuDialog(dm, self)
        if dialog.exec():
            new_props = dialog.get_properties()
            if not new_props[EditorField.MSG]:
                if QMessageBox.question(self, "确认删除", "内容为空，是否直接删除该条弹幕？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                    self.controller.delete_items([uid])
            else:
                if self.controller.update_properties(uid, new_props):
                    self.table.selectRow(row)

    def _insert_row(self, row: int, position: InsertPosition):
        """插入新弹幕"""
        uid = self.model.get_item_id(row)
        if not uid:
            return

        new_uid = self.controller.insert_item(uid, position)
        if new_uid:
            self.preview_mode_cb.setChecked(True)

            row_idx = self._select_row_by_uid(new_uid)
            if row_idx >= 0:
                self._edit_row(row_idx)

    def _shift_selected_items_time(self):
        """上下文菜单：平移用户选中的弹幕"""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        # 收集选中的 UUID
        uids = [
            uid for row_idx in selected_rows
            if (uid := self.model.get_item_id(row_idx.row())) is not None
        ]

        self._prompt_time_offset(uids)

    def _generate_array(self, row: int):
        """生成弹幕阵列"""
        uid = self.model.get_item_id(row)
        if not uid:
            return

        dialog = ArrayGeneratorDialog(self)
        if dialog.exec():
            params = dialog.get_params()

            new_uids = self.controller.generate_array(
                ref_uid=uid,
                text=params["text"],
                mode=params["mode"],
                count=params["count"],
                color_strategy=params["color_strategy"]
            )

            self.preview_mode_cb.setChecked(True)
            self._select_row_by_uid(new_uids[0])

    def _delete_selected_items(self):
        """批量删除选中项"""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        # 收集所有的 UUID
        uids = [
            uid for row_idx in selected_rows
            if (uid := self.model.get_item_id(row_idx.row())) is not None
        ]

        self.controller.delete_items(uids)

    @Slot()
    def _undo(self):
        """撤销"""
        self.controller.undo()

    # endregion
    # region Batch Processing

    @Slot()
    def _batch_remove_newlines(self):
        mod, dele = self.controller.batch_remove_newlines()
        if mod > 0 or dele > 0:
            QMessageBox.information(self, "处理完成", f"修复: {mod} 条\n删除: {dele} 条")
        else:
            QMessageBox.information(self, "无变化", "未发现相关问题。")

    @Slot()
    def _batch_truncate_length(self):
        count = self.controller.batch_truncate()
        if count > 0:
            QMessageBox.information(self, "处理完成", f"已截断 {count} 条过长弹幕。")
        else:
            QMessageBox.information(self, "无变化", "未发现过长弹幕。")

    @Slot()
    def _prompt_time_offset(self, uids: list[str] | None = None):
        """弹出时间平移对话框，处理全局或局部时间轴平移"""
        # 全局平移时，如果没有数据直接返回
        if not uids and not self.controller.has_data:
            return

        dlg = TimeOffsetDialog(self)
        # 根据是否有特定 uids 动态调整标题
        title = f"平移选中的 {len(uids)} 条弹幕" if uids else "整体平移时间轴"
        dlg.setWindowTitle(title)

        if not dlg.exec():
            return

        offset_ms = dlg.get_offset_ms()
        count = self.controller.shift_time(offset_ms, target_uids=uids)

        if count > 0:
            self.logger.info(f"成功平移了 {count} 条弹幕的时间轴。")
        else:
            self.logger.info("平移操作未导致任何数据变化。")

    # endregion

    # --- Qt Methods ---
    def showEvent(self, event):
        super().showEvent(event)

        # 数据已在 __init__ 中加载，仅刷新 UI 状态
        self._update_ui_state()