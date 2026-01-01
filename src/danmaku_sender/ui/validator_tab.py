import logging
from tkinter import Menu

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox, Querybox

from ..core.bili_danmaku_utils import format_ms_to_hhmmss
from ..config.shared_data import SharedDataModel
from ..core.validator_session import ValidatorSession


class ValidatorTab(ttk.Frame):
    """用于验证和修改弹幕的UI标签页 (View层)"""
    def __init__(self, parent, model: SharedDataModel, app):
        super().__init__(parent, padding=15)
        self.model = model
        self.app = app
        self.logger = logging.getLogger("ValidatorTab")
        
        self.session = ValidatorSession(model)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._create_widgets()

    def _create_widgets(self):
        """创建并布局此标签页中的所有UI控件"""
        # --- 顶部控制栏 ---
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=X, padx=5, pady=5)

        # 开始验证按钮
        self.run_validation_button = ttk.Button(top_frame, text="开始验证", command=self.run_validation, bootstyle=PRIMARY, takefocus=False)
        self.run_validation_button.pack(side=LEFT, padx=(0, 10))

        # 批量修复
        # 默认状态是 disabled，只有验证出问题后才启用
        self.batch_mb = ttk.Menubutton(top_frame, text="批量修复", bootstyle=OUTLINE + PRIMARY, state=DISABLED)
        self.batch_mb.pack(side=LEFT, padx=(0, 10))

        # 创建下拉菜单
        self.batch_menu = Menu(self.batch_mb, tearoff=0)
        self.batch_menu.add_command(label="一键去除所有换行符", command=self.batch_remove_newlines)
        self.batch_menu.add_command(label="一键截断过长弹幕(>100字)", command=self.batch_truncate_length)
        self.batch_mb['menu'] = self.batch_menu

        # 撤销按钮
        self.undo_button = ttk.Button(top_frame, text="撤销上次修改", command=self.undo, bootstyle=OUTLINE + WARNING, takefocus=False)
        self.undo_button.pack(side=LEFT, padx=(0, 10))

        # 状态提示文字
        self.status_label = ttk.Label(top_frame, text="提示: 请先在“发射器”页面加载文件并选择分P。", bootstyle=SECONDARY)
        self.status_label.pack(side=LEFT, fill=X, expand=True)

        # --- 中间 Treeview 弹幕列表区域 ---
        tree_frame = ttk.Labelframe(self, text="问题弹幕列表", padding=10)
        tree_frame.pack(expand=True, fill=BOTH, padx=5, pady=10)
        
        columns = ("row_idx", "time", "issue", "content")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", bootstyle=PRIMARY)
        
        self.tree.heading("row_idx", text="行号")
        self.tree.heading("time", text="时间")
        self.tree.heading("issue", text="问题描述")
        self.tree.heading("content", text="弹幕内容 (双击可编辑)")
        
        self.tree.column("row_idx", width=60, stretch=False, anchor=CENTER)
        self.tree.column("time", width=80, stretch=False, anchor=CENTER)
        self.tree.column("issue", width=150, stretch=False)
        self.tree.column("content", stretch=True)
        
        # 滚动条
        vsb = ttk.Scrollbar(tree_frame, orient=VERTICAL, command=self.tree.yview)
        vsb.pack(side=RIGHT, fill=Y)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(expand=True, fill=BOTH)
        
        # 绑定双击编辑事件
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        # --- 底部操作栏 ---
        bottom_frame = ttk.Frame(self)
        bottom_frame.pack(fill=X, pady=10)
        
        self.delete_button = ttk.Button(bottom_frame, text="删除选中条目", command=self.delete_selected_item, bootstyle=DANGER, state=DISABLED, takefocus=False)
        self.delete_button.pack(side=LEFT)
        
        self.apply_button = ttk.Button(bottom_frame, text="应用所有修改", command=self.apply_changes, bootstyle=SUCCESS, state=DISABLED, takefocus=False)
        self.apply_button.pack(side=RIGHT)

    def undo(self):
        """撤销上一次修改"""
        if self.session.undo():
            self._refresh_tree_view()
            self.status_label.config(text="撤销成功。", bootstyle=INFO)
        else:
            self.logger.info("无可撤销的操作。")

    def run_validation(self):
        """运行弹幕验证"""
        if not self.model.loaded_danmakus:
            Messagebox.show_warning("请先在 “发射器” 页面加载弹幕文件。", "无法验证", parent=self.app)
            self.status_label.config(text="验证失败: 未加载文件", bootstyle=DANGER)
            return
        
        if self.model.selected_cid is None:
            Messagebox.show_warning("请先在 “发射器” 页面选择一个分P。", "无法验证", parent=self.app)
            self.status_label.config(text="验证失败: 未选择分P", bootstyle=DANGER)
            return
        
        if self.session.is_dirty:
            if not Messagebox.okcancel("⚠️ 警告：当前有未应用的修改，继续验证将丢弃这些修改。是否继续？", "确认继续", parent=self.app):
                return
            
        self.status_label.config(text="正在验证...", bootstyle=SECONDARY)
        has_issues = self.session.load_and_validate(self.model.selected_part_duration_ms)
        self._refresh_tree_view()
        
        if not has_issues:
            self.status_label.config(text="✅ 验证通过: 所有弹幕均符合规范！", bootstyle=SUCCESS)
            Messagebox.show_info("验证通过", "所有弹幕均符合规范！", parent=self.app)
            self._set_action_buttons_state(False)
        else:
            issue_count = len(self.session.current_issues)
            self.status_label.config(text=f"❌ 发现 {issue_count} 条问题弹幕，请处理。", bootstyle=DANGER)
            self._set_action_buttons_state(True)

    def _refresh_tree_view(self):
        """刷新Treeview中的数据"""
        self.tree.delete(*self.tree.get_children())
        
        items = self.session.get_display_items()

        for item in items:
            self.tree.insert("", END, iid=str(item['original_index']), values=(
                item['original_index'] + 1,
                format_ms_to_hhmmss(item['time_ms']),
                item['reason'],
                item['current_content']
            ))

        if self.session.can_undo:
            self.undo_button.config(state=NORMAL)
        else:
            self.undo_button.config(state=DISABLED)
        
        if self.session.is_dirty:
            self.status_label.config(text="⚠️ 有未应用的修改！请点击“应用所有修改”按钮。", bootstyle=WARNING)
        elif self.session.has_active_session:
            self.status_label.config(text="当前无未保存修改。", bootstyle=SECONDARY)

    def batch_remove_newlines(self):
        """批量去除所有问题弹幕中的换行符"""
        modified_count, deleted_count = self.session.batch_remove_newlines()

        if modified_count > 0 or deleted_count > 0:
            self._refresh_tree_view()
            Messagebox.show_info(
                message=f"批量处理完成！\n修复: {modified_count} 条 | 删除: {deleted_count} 条",
                title="处理结果",
                parent=self.app
            )
        else:
            Messagebox.show_info("未发现包含换行符的弹幕。", "无变化", parent=self.app)

    def batch_truncate_length(self):
        """批量截断所有过长弹幕 (>100字)"""
        count = self.session.batch_truncate_length(limit=100)

        if count > 0:
            self._refresh_tree_view()
            Messagebox.show_info(f"已批量截断 {count} 条过长弹幕 (内容)。", "处理完成", parent=self.app)
        else:
            Messagebox.show_info("未发现过长弹幕。", "无变化", parent=self.app)

    def on_tree_double_click(self, event):
        """双击单元格进行编辑"""
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return

        if self.tree.identify_column(event.x) != "#4":
            return

        selected_iid = self.tree.focus()
        if not selected_iid:
            return

        current_text = self.tree.item(selected_iid, "values")[3]  # 获取当前值
        new_text = Querybox.get_string(
            prompt="请输入修改后的弹幕内容：", 
            title="编辑弹幕", 
            initialvalue=current_text,
            parent=self.app
        )
        
        if new_text is not None:
            clean_text = new_text.strip()
            idx = int(selected_iid)

            if clean_text:
                if clean_text != current_text:
                    self.session.update_item_content(idx, clean_text)
                    self._refresh_tree_view()
            else:
                if Messagebox.okcancel("内容为空，是否删除该条弹幕？", "确认删除", parent=self.app):
                    self.session.delete_item(idx)
                    self._refresh_tree_view()

    def delete_selected_item(self):
        """删除在Treeview中选中的条目"""
        selected_items = self.tree.selection()
        if not selected_items:
            Messagebox.show_warning("请先选择要删除的弹幕条目。", "未选择", parent=self.app)
            return
        
        for iid in selected_items:
            self.session.delete_item(int(iid))
            
        self._refresh_tree_view()

    def apply_changes(self):
        """应用更改"""
        if not self.session.has_active_session:
            Messagebox.show_warning("请先运行一次验证，再应用修改。", "未进行验证", parent=self.app)
            return
        
        total, fixed, deleted = self.session.apply_changes()
        
        self.logger.info(f"修改已应用: 修复 {fixed}, 删除 {deleted}")
        Messagebox.show_info( 
            f"已更新发送队列！\n\n保留(修复): {fixed} 条 | 移除(删除): {deleted} 条\n\n现在的弹幕总数: {total}", 
            "应用成功",
            parent=self.app
        )

        self._refresh_tree_view()
        self.status_label.config(text="修改已应用。", bootstyle=SECONDARY)
        self._set_action_buttons_state(False)

    def _set_action_buttons_state(self, enabled: bool):
        """统一控制按钮状态"""
        state = NORMAL if enabled else DISABLED
        self.batch_mb.config(state=state)
        self.delete_button.config(state=state)
        self.apply_button.config(state=state)
        if not enabled:
            self.undo_button.config(state=DISABLED)