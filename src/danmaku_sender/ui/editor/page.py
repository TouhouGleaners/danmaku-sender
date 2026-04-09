import logging
from typing import Any

from PySide6.QtCore import Qt, QModelIndex, QPoint, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableView, QHeaderView, QAbstractItemView, QMessageBox,
    QMenu, QFrame, QCheckBox, QSplitter, QFileDialog
)

from .components import EditorTableModel, ValidationRulesGroup, PropertyInspectorGroup
from .dialogs import EditDanmakuDialog, TimeOffsetDialog, ArrayGeneratorDialog
from ..framework.style_loader import get_svg_icon
from ..controllers.editor_controller import EditorController

from ...core.types.editor_types import EditorField, InsertPosition
from ...core.state import AppState
from ...core.services.danmaku_exporter import export_danmakus_to_xml


class EditorPage(QWidget):
    def __init__(self):
        super().__init__()
        self.controller: EditorController | None = None
        self.logger = logging.getLogger("App.System.UI.Editor")

        self.current_item_id: str | None = None

        self._create_ui()

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
        self.btn_new = QPushButton(get_svg_icon("note_add.svg"), "新建")
        self.btn_new.clicked.connect(self._create_new_file)

        self.btn_import = QPushButton(get_svg_icon("file_open.svg"), "导入 XML")
        self.btn_import.clicked.connect(self._import_xml)

        self.btn_export = QPushButton(get_svg_icon("file_save.svg"), "导出为 XML")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export_xml)

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
        self.batch_menu.addAction(get_svg_icon("format_clear.svg"), "一键去除所有换行符", self._batch_remove_newlines)
        self.batch_menu.addAction(get_svg_icon("short_text.svg"), "一键截断过长弹幕(>100字)", self._batch_truncate_length)
        self.batch_menu.addAction(get_svg_icon("sync_alt.svg"), "整体平移时间轴", self._open_offset_dialog)
        self.btn_batch.setMenu(self.batch_menu)

        toolbar_layout.addWidget(self.btn_batch)
        toolbar_layout.addStretch()

        # C: 核心工作流
        self.undo_btn = QPushButton(get_svg_icon("undo.svg"), "撤销")
        self.undo_btn.setFixedWidth(80)
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self._undo)

        self.run_btn = QPushButton(get_svg_icon("play_arrow.svg"), "开始校验")
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
        self.apply_btn.clicked.connect(self._apply_changes)

        bottom_layout.addWidget(self.status_label, stretch=1)
        bottom_layout.addWidget(self.apply_btn)

        main_layout.addLayout(bottom_layout)

        self._update_ui_state()

    def bind_state(self, state: AppState):
        """将 UI 控件与 AppState 进行双向绑定"""
        if self.controller and self.controller.state is state:
            return

        self.controller = EditorController(state, self)
        self.controller.dataChanged.connect(self._refresh_table)

        self.rules_group.bind_state(state)
        self._update_ui_state()

    # endregion
    # region State & UI Refresh Updates

    def _update_ui_state(self):
        """统一状态机控制"""
        if not self.controller:
            for btn in [self.run_btn, self.btn_batch, self.undo_btn, self.apply_btn, self.btn_export, self.btn_new]:
                btn.setEnabled(False)
            self.status_label.setText("提示: 请在“发射器”页面加载 XML，或点击新建。")
            self.status_label.setStyleSheet("color: #7f8c8d;")
            return

        ctrl = self.controller

        self.btn_new.setEnabled(True)
        self.btn_import.setEnabled(True)
        self.run_btn.setEnabled(ctrl.source_data_exists)
        self.btn_batch.setEnabled(ctrl.has_data)
        self.btn_export.setEnabled(ctrl.has_data)
        self.undo_btn.setEnabled(ctrl.can_undo)
        self.apply_btn.setEnabled(ctrl.is_dirty)

        if ctrl.is_dirty:
            self.status_label.setText("⚠️ 有未应用的修改！请点击“应用所有修改”按钮。")
            self.status_label.setStyleSheet("color: #d35400;")
        elif ctrl.has_data:
            if ctrl.active_error_count > 0:
                self.status_label.setText(f"❌ 发现 {ctrl.active_error_count} 条问题弹幕，请处理。")
                self.status_label.setStyleSheet("color: red;")
            else:
                mode_str = " (深度校验)" if ctrl.has_video_context else " (无视频关联，跳过时间检查)"
                self.status_label.setText(f"✅ 验证通过，当前无问题{mode_str}。")
                self.status_label.setStyleSheet("color: green;")
        else:
            self.status_label.setText("提示: 点击“开始校验”以加载并检查弹幕。")
            self.status_label.setStyleSheet("color: #7f8c8d;")

    @Slot()
    def _refresh_table(self):
        """刷新表格"""
        if self.controller:
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
        if uid and self.controller:
            self.current_item_id = uid
            if dm := self.controller.get_item_danmaku(uid):
                self.inspector_group.load_danmaku(dm)

    # endregion
    # region Core Workflow (File & Validation)

    @Slot()
    def _create_new_file(self):
        if not self.controller:
            return

        if self.controller.is_dirty:
            reply = QMessageBox.question(self, "放弃修改?", "当前有未应用的修改，新建将丢失这些数据。\n是否继续？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return

        self.controller.create_new_workspace()
        self.preview_mode_cb.setChecked(True)
        self.current_item_id = None
        self.inspector_group.reset_inspector()
        QMessageBox.information(self, "新建成功", "已创建空白工作区，你可以开始创作了！")

    @Slot()
    def _import_xml(self):
        if not self.controller:
            return

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
            try:
                count = self.controller.import_xml_workspace(file_path)
                if count > 0:
                    self.preview_mode_cb.setChecked(True)
                    self.current_item_id = None
                    self.inspector_group.reset_inspector()
                    QMessageBox.information(
                        self, "导入成功",
                        f"成功导入 {count} 条弹幕！\n(当前为无视频上下文模式，已跳过时间越界检查)"
                    )
                else:
                    QMessageBox.warning(self, "导入失败", "未从文件中解析出有效的弹幕。")
            except Exception as e:
                QMessageBox.critical(self, "导入失败", f"解析 XML 时发生错误:\n{e}")

    @Slot()
    def _export_xml(self):
        """将当前工作区内容导出为 XML 文件"""
        if not self.controller:
            return

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
            try:
                export_danmakus_to_xml(working_dms, file_path)
                QMessageBox.information(
                    self,
                    "导出成功",
                    f"🎉 成功导出 {len(working_dms)} 条弹幕至：\n{file_path}"
                )
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"文件写入失败，请检查路径权限。\n错误信息:\n{e}")

    @Slot()
    def _run_validation(self):
        """运行验证逻辑"""
        if not self.controller:
            return

        # 校验前置条件
        if not self.controller.source_data_exists:
            QMessageBox.warning(self, "无法验证", "当前工作区为空，请先新建或加载弹幕。")
            return

        # 检查未保存修改
        if self.controller.is_dirty:
            reply = QMessageBox.question(
                self,
                "确认",
                "当前有未应用的修改，重新验证将丢弃这些修改。\n是否继续？",
                buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        if not self.controller.has_video_context:
            QMessageBox.information(
                self,
                "降级校验模式",
                "当前未关联目标视频（无 BVID/分P 信息）。\n\n系统将以【降级模式】执行校验：\n✔️ 检查文本长度、换行符、屏蔽词\n⏭️ 跳过弹幕发送时间是否超出视频总时长的检查"
            )

        # 执行验证
        self.status_label.setText("正在验证...")
        self.status_label.setStyleSheet("color: blue;")

        self.current_item_id = None
        self.inspector_group.reset_inspector()

        has_issues = self.controller.load_from_state()
        if not has_issues:
            QMessageBox.information(self, "验证通过", "所有弹幕均符合当前规范！")

    @Slot()
    def _apply_changes(self):
        """应用修改"""
        if not self.controller:
            return

        self.current_item_id = None
        self.inspector_group.reset_inspector()

        total, fixed, deleted = self.controller.commit_to_state()

        self.logger.info(f"修改已应用: 修复 {fixed}, 删除 {deleted}")
        QMessageBox.information(
            self,
            "应用成功",
            f"发送队列已更新！\n\n修复: {fixed} 条\n移除: {deleted} 条\n剩余总数: {total} 条"
        )

    # endregion
    # region Item Operations (Row Level & Dialogs)

    def _apply_properties(self, new_props: dict[EditorField, Any]):
        """Inspector 回调：应用弹幕属性修改"""
        if self.current_item_id and self.controller:
            if self.controller.update_properties(self.current_item_id, new_props):
                for i in range(self.model.rowCount()):
                    if self.model.get_item_id(i) == self.current_item_id:
                        self.table.selectRow(i)
                        break

    @Slot(QPoint)
    def _open_context_menu(self, pos: QPoint):
        """打开表格右键上下文菜单"""
        index = self.table.indexAt(pos)
        if not index.isValid() or not self.controller:
            return

        menu = QMenu(self)
        row = index.row()

        menu.addAction(get_svg_icon("edit.svg"), "编辑内容", lambda: self._edit_row(row))
        menu.addSeparator()
        menu.addAction(get_svg_icon("vertical_align_top.svg"), "在上方插入新弹幕", lambda: self._insert_row(row, InsertPosition.ABOVE))
        menu.addAction(get_svg_icon("vertical_align_bottom.svg"), "在下方插入新弹幕", lambda: self._insert_row(row, InsertPosition.BELOW))
        menu.addSeparator()
        menu.addAction(get_svg_icon("sync_alt.svg"), "平移选中弹幕的时间轴", self._shift_selected_items_time)
        adv_menu = menu.addMenu(get_svg_icon("auto_awesome.svg"), "高级生成工具")
        adv_menu.addAction(get_svg_icon("gradient.svg"), "生成彩虹弹幕阵列", lambda: self._generate_array(row))
        menu.addAction(get_svg_icon("delete.svg"), "删除选中条目", self._delete_selected_items)

        # 弹出菜单
        menu.exec(self.table.viewport().mapToGlobal(pos))

    @Slot(QModelIndex)
    def _on_table_double_click(self, index: QModelIndex):
        """双击编辑内容"""
        if index.column() == 3:
            self._edit_row(index.row())

    def _edit_row(self, row):
        if not self.controller:
            return

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
        if not self.controller:
            return

        uid = self.model.get_item_id(row)
        if not uid:
            return

        new_uid = self.controller.insert_item(uid, position)
        if new_uid:
            self.preview_mode_cb.setChecked(True)

            for i in range(self.model.rowCount()):
                if self.model.get_item_id(i) == new_uid:
                    self.table.selectRow(i)
                    self._edit_row(i)
                    break

    def _shift_selected_items_time(self):
        """平移用户选中的弹幕"""
        if not self.controller:
            return

        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        # 收集选中的 UUID
        uids = [
            uid for row_idx in selected_rows
            if (uid := self.model.get_item_id(row_idx.row())) is not None
        ]

        if not uids:
            return

        # 复用弹窗，动态修改标题以区分“全局”和“局部”
        dlg = TimeOffsetDialog(self)
        dlg.setWindowTitle(f"平移选中的 {len(uids)} 条弹幕")

        if dlg.exec():
            offset_ms = dlg.get_offset_ms()
            count = self.controller.shift_time(offset_ms, target_uids=uids)

            if count > 0:
                self.logger.info(f"成功平移了 {count} 条选中弹幕的时间轴。")
            else:
                self.logger.info("平移操作未导致任何数据变化。")

    def _generate_array(self, row: int):
        """生成弹幕阵列"""
        if not self.controller:
            return

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

            if new_uids:
                self.preview_mode_cb.setChecked(True)

                for i in range(self.model.rowCount()):
                    if self.model.get_item_id(i) == new_uids[0]:
                        self.table.selectRow(i)
                        break

    def _delete_selected_items(self):
        """批量删除选中项"""
        if not self.controller:
            return

        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        # 收集所有的 UUID
        uids = [
            uid for row_idx in selected_rows
            if (uid := self.model.get_item_id(row_idx.row())) is not None
        ]

        if uids:
            self.controller.delete_items(uids)

    @Slot()
    def _undo(self):
        """撤销"""
        if self.controller:
            self.controller.undo()

    # endregion
    # region Batch Processing

    @Slot()
    def _batch_remove_newlines(self):
        if not self.controller:
            return

        mod, dele = self.controller.batch_remove_newlines()
        if mod > 0 or dele > 0:
            QMessageBox.information(self, "处理完成", f"修复: {mod} 条\n删除: {dele} 条")
        else:
            QMessageBox.information(self, "无变化", "未发现相关问题。")

    @Slot()
    def _batch_truncate_length(self):
        if not self.controller:
            return

        count = self.controller.batch_truncate()
        if count > 0:
            QMessageBox.information(self, "处理完成", f"已截断 {count} 条过长弹幕。")
        else:
            QMessageBox.information(self, "无变化", "未发现过长弹幕。")

    @Slot()
    def _open_offset_dialog(self):
        if not self.controller or not self.controller.has_data:
            return

        dlg = TimeOffsetDialog(self)
        if dlg.exec():
            offset_ms = dlg.get_offset_ms()
            count = self.controller.shift_time(offset_ms)

            if count > 0:
                self.logger.info(f"成功平移了 {count} 条选中弹幕的时间轴。")
            else:
                self.logger.info("平移操作未导致任何数据变化。")

    # endregion

    # --- Qt Methods ---
    def showEvent(self, event):
        super().showEvent(event)

        if not self.controller:
            return

        # 如果全局状态里有数据 (比如刚在发射器加载了)，但编辑器是空的
        if self.controller.source_data_exists and not self.controller.has_data:
            self.logger.info("检测到外部加载了新数据，自动检出到编辑器沙盒并执行基础校验。")
            self.controller.load_from_state()

        self._update_ui_state()