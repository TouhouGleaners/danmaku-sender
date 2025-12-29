import logging
import copy
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox, Querybox
from tkinter import Menu

from ..core.bili_danmaku_utils import validate_danmaku_list, format_ms_to_hhmmss
from ..config.shared_data import SharedDataModel


class ValidatorTab(ttk.Frame):
    """用于验证和修改弹幕的UI标签页"""
    def __init__(self, parent, model: SharedDataModel, app):
        super().__init__(parent, padding=15)
        self.model = model
        self.app = app
        self.logger = logging.getLogger("ValidatorTab")
        self.original_danmakus_snapshot = []
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

    def run_validation(self):
        """运行弹幕验证并显示结果"""
        self.tree.delete(*self.tree.get_children())

        if not self.model.loaded_danmakus:
            Messagebox.show_warning("请先在 “发射器” 页面加载弹幕文件。", "无法验证", parent=self.app)
            return
        
        if self.model.selected_cid is None:
            Messagebox.show_warning("请先在 “发射器” 页面选择一个分P。\n（需要分P时长来检查时间戳）", "无法验证", parent=self.app)
            return
        
        # 创建快照，防止直接修改 SharedModel
        self.original_danmakus_snapshot = copy.deepcopy(self.model.loaded_danmakus)
        duration_ms = self.model.selected_part_duration_ms

        self.logger.info(f"开始验证弹幕，共 {len(self.model.loaded_danmakus)} 条，分P时长 {duration_ms / 1000} 秒。")
        
        issues = validate_danmaku_list(self.original_danmakus_snapshot, duration_ms)
        if not issues:
            self.status_label.config(text="✅ 验证通过: 所有弹幕均符合规范！", bootstyle=SUCCESS)
            Messagebox.show_info("验证通过", "所有弹幕均符合规范！", parent=self.app)
            self._set_action_buttons_state(False) # 禁用操作按钮
        else:
            self.status_label.config(text=f"❌ 发现 {len(issues)} 条问题弹幕，请处理。", bootstyle=DANGER)

            for issue in issues:
                self.tree.insert("", "end", iid=str(issue['original_index']), values=(
                    issue['original_index'] + 1,
                    format_ms_to_hhmmss(issue['danmaku'].get('progress', 0)),
                    issue['reason'],
                    issue['danmaku']['msg']
                ))

            self._set_action_buttons_state(True) # 启用操作按钮

    def batch_remove_newlines(self):
        """批量去除所有问题弹幕中的换行符"""
        modified_count = 0
        deleted_count = 0

        for item_id in self.tree.get_children():
            values = self.tree.item(item_id, "values")
            content = values[3]

            if '\n' in content or '\\n' in content or '/n' in content:
                new_content = content.replace('\n', '').replace('\\n', '').replace('/n', '')
                self.tree.set(item_id, column="content", value=new_content)
                if not new_content.strip():
                    # 如果处理后只剩空白，直接从列表中删除
                    self.tree.delete(item_id)
                    deleted_count += 1
                else:
                    # 如果不为空，更新内容
                    self.tree.set(item_id, column="content", value=new_content)
                    modified_count += 1
        
        if modified_count > 0 or deleted_count > 0:
            msg = f"批量处理完成！\n\n- 内容修复: {modified_count} 条\n- 变成空白已删除: {deleted_count} 条"
            Messagebox.show_info(msg, "处理结果", parent=self.app)
        else:
            Messagebox.show_info("未发现包含换行符的弹幕。", "无变化", parent=self.app)

    def batch_truncate_length(self):
        """批量截断所有过长弹幕 (>100字)"""
        count = 0
        for item_id in self.tree.get_children():
            values = self.tree.item(item_id, "values")
            content = values[3]

            if len(content) > 100:
                new_content = content[:100]
                self.tree.set(item_id, column="content", value=new_content)
                count += 1
        
        self._show_batch_result(count, "过长内容")

    def _show_batch_result(self, count: int, action_name: str):
        if count > 0:
            Messagebox.show_info(f"已批量处理 {count} 条弹幕 ({action_name})。", "处理完成", parent=self.app)
        else:
            Messagebox.show_info(f"未发现需要进行 ({action_name}) 处理的弹幕。", "无变化", parent=self.app)

    def on_tree_double_click(self, event):
        """双击单元格进行编辑"""
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell": return
        
        column = self.tree.identify_column(event.x)
        if column != "#4": return # 只允许编辑内容列
        
        selected_iid = self.tree.focus()
        if not selected_iid: return
        
        # 获取当前值
        current_text = self.tree.item(selected_iid, "values")[3]

        # 弹出输入框让用户编辑
        new_text = Querybox.get_string(
            prompt="请输入修改后的弹幕内容：", 
            title="编辑弹幕", 
            initialvalue=current_text,
            parent=self.app
        )
        
        if new_text is not None:
            # 去除首尾空格，防止误操作
            clean_text = new_text.strip()
            if clean_text:
                self.tree.set(selected_iid, column="content", value=clean_text)
            else:
                # 如果用户把内容删光了点确定，询问是否要删除这条
                if Messagebox.okcancel("内容为空，是否删除该条弹幕？", "确认删除", parent=self.app):
                    self.tree.delete(selected_iid)

    def delete_selected_item(self):
        """删除在Treeview中选中的条目"""
        selected_items = self.tree.selection()
        if not selected_items:
            Messagebox.show_warning("请先选择要删除的弹幕条目。", "未选择", parent=self.app)
            return
        
        for item in selected_items:
            self.tree.delete(item)

    def apply_changes(self):
        """应用更改，重建并更新共享模型中的弹幕列表"""
        if not self.original_danmakus_snapshot:
            Messagebox.show_warning("请先运行一次验证，再应用修改。", "未进行验证", parent=self.app)
            return
        
        # 获取所有还在列表里的问题弹幕 (ID -> 最新内容)
        remaining_issues_map = {}
        for item_id in self.tree.get_children():
            values = self.tree.item(item_id, "values")
            new_msg = values[3]
            remaining_issues_map[int(item_id)] = new_msg

        # 重建列表
        new_danmaku_list = []
        deleted_count = 0
        fixed_count = 0

        for i, dm_snapshot in enumerate(self.original_danmakus_snapshot):
            # 如果它原本就是合法的，直接保留
            if dm_snapshot.get('is_valid', False):
                new_danmaku_list.append(dm_snapshot)
                continue
            
            # 如果它是不合法的
            if i in remaining_issues_map:
                # 还在列表里 -> 说明用户修改了它 (或者没修直接点应用，也算保留)
                # 使用修改后的内容
                dm_snapshot['msg'] = remaining_issues_map[i]
                # 假设只要还在列表里，用户就认可了它的内容，我们标记为有效
                dm_snapshot['is_valid'] = True 
                new_danmaku_list.append(dm_snapshot)
                fixed_count += 1
            else:
                # 不在列表里 -> 说明用户把它删了
                deleted_count += 1
        
        self.model.loaded_danmakus = new_danmaku_list
        
        self.logger.info(f"修改已应用: 修复 {fixed_count} 条, 删除 {deleted_count} 条。")
        Messagebox.show_info( 
            f"已更新发送队列！\n\n保留(修复): {fixed_count} 条\n移除(删除): {deleted_count} 条\n\n现在的弹幕总数: {len(new_danmaku_list)}", 
            "应用成功",
            parent=self.app
        )
        
        # 清理现场
        self.tree.delete(*self.tree.get_children())
        self.original_danmakus_snapshot = []
        self.status_label.config(text="修改已应用。", bootstyle=SECONDARY)
        self._set_action_buttons_state(False)

    def _set_action_buttons_state(self, enabled: bool):
        """统一控制按钮状态"""
        state = NORMAL if enabled else DISABLED
        self.batch_mb.config(state=state)
        self.delete_button.config(state=state)
        self.apply_button.config(state=state)