import logging
import copy
from tkinter import ttk, messagebox
from ttkbootstrap.dialogs import Messagebox

from bili_danmaku_utils import validate_danmaku_list, format_ms_to_hhmmss
from shared_data import SharedDataModel


class ValidatorTab(ttk.Frame):
    """用于验证和修改弹幕的UI标签页"""
    def __init__(self, parent, model: SharedDataModel, app):
        super().__init__(parent)
        self.model = model
        self.app = app
        self.logger = logging.getLogger("ValidatorTab")
        self.original_danmakus_snapshot = []

        self._create_widgets()

    def _create_widgets(self):
        """创建并布局此标签页中的所有UI控件"""
        top_frame = ttk.Frame(self)
        top_frame.pack(fill="x", padx=10, pady=5)
        self.run_validation_button = ttk.Button(top_frame, text="开始验证", command=self.run_validation, takefocus=0)
        self.run_validation_button.pack(side='left', padx=(0, 10))
        self.status_label = ttk.Label(top_frame, text="提示: 请先在“发射器”页面加载文件并选择分P。")
        self.status_label.pack(side='left', fill='x', expand=True)
        tree_frame = ttk.Labelframe(self, text="问题弹幕列表", padding=10)
        tree_frame.pack(expand=True, fill='both', padx=10, pady=5)
        
        columns = ("#1", "#2", "#3", "#4")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings")
        self.tree.heading("#1", text="原始行号")
        self.tree.heading("#2", text="弹幕时间")
        self.tree.heading("#3", text="问题描述")
        self.tree.heading("#4", text="弹幕内容 (双击可编辑)")
        self.tree.column("#1", width=80, stretch=False, anchor='center')
        self.tree.column("#2", width=100, stretch=False, anchor='center')
        self.tree.column("#3", width=140, stretch=False)
        self.tree.column("#4", stretch=True)
        
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        vsb.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(expand=True, fill='both')
        
        self.tree.bind("<Double-1>", self.on_tree_double_click)
        bottom_frame = ttk.Frame(self)
        bottom_frame.pack(fill='x', padx=10, pady=10)
        
        self.delete_button = ttk.Button(bottom_frame, text="删除选中条目", command=self.delete_selected_item, bootstyle="danger", takefocus=0)
        self.delete_button.pack(side='left', padx=5)
        
        self.apply_button = ttk.Button(bottom_frame, text="应用所有修改", command=self.apply_changes, bootstyle="success", takefocus=0)
        self.apply_button.pack(side='right', padx=5)

    def run_validation(self):
        """运行弹幕验证并显示结果"""
        self.tree.delete(*self.tree.get_children())

        if not self.model.loaded_danmakus:
            Messagebox.show_warning("请先在“发射器”页面加载弹幕文件。", "错误", parent=self.app)
            return
        
        if self.model.selected_cid is None:
            Messagebox.show_warning("请先在“发射器”页面选择一个分P。\n（需要分P时长来检查时间戳）", "错误", parent=self.app)
            return
        
        self.original_danmakus_snapshot = copy.deepcopy(self.model.loaded_danmakus)
        duration_ms = self.model.selected_part_duration_ms

        self.logger.info(f"开始验证弹幕，共 {len(self.model.loaded_danmakus)} 条，分P时长 {duration_ms / 1000} 秒。")
        
        issues = validate_danmaku_list(self.original_danmakus_snapshot, duration_ms)
        if not issues:
            self.status_label.config(text=f"验证完成: {len(self.original_danmakus_snapshot)} 条弹幕均符合规范！")
            Messagebox.show_info("验证通过", "所有弹幕均符合规范！", parent=self.app)
        else:
            self.status_label.config(text=f"验证完成: 发现 {len(issues)} 条问题弹幕，请查看下方列表。")
            for issue in issues:
                self.tree.insert("", "end", iid=str(issue['original_index']), values=(
                    issue['original_index'] + 1,
                    format_ms_to_hhmmss(issue['danmaku'].get('progress', 0)),
                    issue['reason'],
                    issue['danmaku']['msg']
                ))

    def on_tree_double_click(self, event):
        """处理双击事件以编辑弹幕内容"""
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell" or self.tree.identify_column(event.x) != "#4":
            return
        
        selected_iid = self.tree.focus()
        if not selected_iid:
            return
        
        column_box = self.tree.bbox(selected_iid, "#4")
        current_text = self.tree.item(selected_iid, "values")[3]

        entry_edit = ttk.Entry(self.tree, font=("TkDefaultFont", 9))
        entry_edit.place(x=column_box[0], y=column_box[1], width=column_box[2], height=column_box[3] + 8)
        entry_edit.insert(0, current_text)
        entry_edit.select_range(0, 'end')
        entry_edit.focus_set()

        def on_commit(event):
            new_text = entry_edit.get()
            self.tree.set(selected_iid, "#4", new_text)
            entry_edit.destroy()

        entry_edit.bind("<FocusOut>", on_commit)
        entry_edit.bind("<Return>", on_commit)

    def delete_selected_item(self):
        """删除在Treeview中选中的条目"""
        selected_items = self.tree.selection()
        if not selected_items:
            Messagebox.show_warning("未选择", "请先选择要删除的弹幕条目。", parent=self.app)
            return
        
        if messagebox.askyesno("确认删除", f"确定要从问题列表中移除这 {len(selected_items)} 条弹幕吗？\n（应用修改后将从发送队列中删除）", parent=self.app):
            for item in selected_items:
                self.tree.delete(item)

    def apply_changes(self):
        """应用更改，重建并更新共享模型中的弹幕列表"""
        if not self.original_danmakus_snapshot:
            Messagebox.show_warning("未进行验证", "请先运行一次验证，再应用修改。", parent=self.app)
            return
        
        modified_issues = {
            int(iid): self.tree.item(iid, "values")[3]
            for iid in self.tree.get_children()
        }

        new_danmaku_list = []
        for idx, dm_snapshot in enumerate(self.original_danmakus_snapshot):
            if dm_snapshot.get('is_valid', False):
                new_danmaku_list.append(dm_snapshot)
            elif idx in modified_issues:
                dm_snapshot['msg'] = modified_issues[idx]
                new_danmaku_list.append(dm_snapshot)
        
        original_count = len(self.model.loaded_danmakus)
        new_count = len(new_danmaku_list)

        self.model.loaded_danmakus = new_danmaku_list

        self.logger.info(f"修改已应用。弹幕数量从 {original_count} 更新为 {new_count}。")
        Messagebox.show_info("应用成功", f"操作成功！\n原弹幕数: {original_count}\n处理后弹幕数: {new_count}", parent=self.app)

        self.tree.delete(*self.tree.get_children())
        self.original_danmakus_snapshot = []
        self.status_label.config(text="修改已应用。如需再次验证，请重新加载文件或运行验证。")