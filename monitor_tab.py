import logging
import threading
from tkinter import scrolledtext
import ttkbootstrap as ttk
from ttkbootstrap.tooltip import ToolTip 
from ttkbootstrap.dialogs import Messagebox

from bili_monitor import BiliDanmakuMonitor


class MonitorTab(ttk.Frame):
    """
    弹幕发送进度监视器标签页。
    提供当前视频/文件信息、高级设置、操作按钮，以及日志显示。
    """
    def __init__(self, parent, model, app):
        """
        初始化监视器标签页。
        
        Args:
            parent: 父级Tkinter组件，通常是ttk.Notebook。
            model: 共享数据模型，包含BVID、文件路径、设置等，实现UI数据绑定。
            app: 主应用实例，用于作为Messagebox等对话框的父窗口。
        """
        super().__init__(parent, padding=15)
        self.model = model
        self.app = app
        self.logger = logging.getLogger("monitor_tab")
        # 配置主Frame的列和行权重
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.monitor_thread = None
        self.stop_monitor_event = threading.Event()
        
        # 绑定来自共享数据模型的变量
        self.current_bvid = self.model.bvid 
        self.current_part = self.model.part_var  
        self.current_file = self.model.danmaku_xml_path 

        self._create_widgets()

    def _create_widgets(self):
        """
        创建并布局监视器标签页的所有UI组件。
        包括视频/文件信息、高级设置、日志区域和底部控制栏。
        """
        
        # --- 监视设置区 ---
        monitor_settings_frame = ttk.Labelframe(self, text="监视设置", padding=15, bootstyle="secondary")
        monitor_settings_frame.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        monitor_settings_frame.columnconfigure(1, weight=1) # 允许第二列的显示内容占据更多空间

        # 当前视频BVID显示：占据一行
        ttk.Label(monitor_settings_frame, text="当前视频:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        ttk.Label(monitor_settings_frame, textvariable=self.current_bvid, font=("TkDefaultFont", 9, "bold"), bootstyle="info").grid(row=0, column=1, columnspan=3, sticky="w") 

        # 当前分P显示：占据一行
        ttk.Label(monitor_settings_frame, text="当前分P:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        ttk.Label(monitor_settings_frame, textvariable=self.current_part, font=("TkDefaultFont", 9, "bold"), bootstyle="info").grid(row=1, column=1, columnspan=3, sticky="w") 

        # 当前弹幕文件路径显示：占据一行
        ttk.Label(monitor_settings_frame, text="当前文件:").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        file_path_label = ttk.Label(monitor_settings_frame, textvariable=self.current_file, font=("TkDefaultFont", 9, "bold"), bootstyle="info", wraplength=400)
        file_path_label.grid(row=2, column=1, columnspan=3, sticky="w")
        
        # 为文件路径标签添加 Tooltip，鼠标悬停时显示完整路径
        self.file_path_tooltip = ToolTip(file_path_label, text="") 
        def update_file_tooltip_text(event):
            self.file_path_tooltip.text = self.current_file.get() 
        file_path_label.bind("<Enter>", update_file_tooltip_text)

        # --- 高级设置区 ---
        advanced_settings_frame = ttk.Labelframe(self, text="高级设置", padding=15, bootstyle="secondary")
        advanced_settings_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        advanced_settings_frame.columnconfigure(1, weight=1) # 允许输入框占据更多空间

        # 检查间隔设置
        ttk.Label(advanced_settings_frame, text="检查间隔(秒):").grid(row=0, column=0, sticky="w", padx=5, pady=8)
        self.interval_entry = ttk.Entry(advanced_settings_frame, width=10, textvariable=self.model.monitor_interval, takefocus=0)
        self.interval_entry.grid(row=0, column=1, sticky="w", padx=(0,10))

        # 时间容差设置
        ttk.Label(advanced_settings_frame, text="时间容差(ms):").grid(row=0, column=2, sticky="w", padx=5, pady=8)
        self.tolerance_entry = ttk.Entry(advanced_settings_frame, width=10, textvariable=self.model.time_tolerance, takefocus=0)
        self.tolerance_entry.grid(row=0, column=3, sticky="w")
    
        
        # --- 运行日志区 ---
        log_frame = ttk.Labelframe(self, text="运行日志", padding=10)
        log_frame.grid(row=2, column=0, padx=10, pady=5, sticky="nsew") 
        log_frame.columnconfigure(0, weight=1) # 日志文本框占据所有水平空间
        log_frame.rowconfigure(0, weight=1)    # 日志文本框占据所有垂直空间
        
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=ttk.WORD, state='disabled', font=("TkDefaultFont", 9))
        self.log_text.grid(row=0, column=0, sticky="nsew")

        # --- 底部控制栏 ---
        # 包含状态、进度条和操作按钮，采用水平布局：[状态标签] [-----进度条-----] [按钮]
        control_bar_frame = ttk.Frame(self, padding=10)
        control_bar_frame.grid(row=3, column=0, padx=10, pady=5, sticky="ew")
        # 配置列权重：状态标签和按钮固定宽度，进度条扩展
        control_bar_frame.columnconfigure(0, weight=0) # 状态标签不扩展
        control_bar_frame.columnconfigure(1, weight=1) # 进度条扩展以填充中间空间
        control_bar_frame.columnconfigure(2, weight=0) # 按钮不扩展

        # 状态标签：显示监视器当前状态，与共享数据模型绑定
        self.status_label = ttk.Label(control_bar_frame, textvariable=self.model.monitor_status_text, style="secondary.TLabel")
        self.status_label.grid(row=0, column=0, sticky="w")

        # 进度条：显示监视任务的进度
        self.progress_bar = ttk.Progressbar(control_bar_frame, mode='determinate', variable=self.model.monitor_progress_var, style='success.Striped.TProgressbar')
        self.progress_bar.grid(row=0, column=1, sticky="ew", padx=(10, 10)) # 左右各有10像素间距

        # 开始/停止监视按钮：控制监视任务的启动/停止
        self.start_button = ttk.Button(
            control_bar_frame, 
            text="开始监视", 
            command=self.toggle_monitoring,
            style="success.TButton", 
            width=12
        )
        self.start_button.grid(row=0, column=2, sticky="e")

    def set_ui_state(self, is_enabled: bool):
        """启用或禁用UI控件，防止任务运行时误操作。"""
        state = 'normal' if is_enabled else 'disabled'
        self.interval_entry.config(state=state)
        self.tolerance_entry.config(state=state)

    def toggle_monitoring(self):
        """切换监视任务的启动/停止状态。"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self):
        """启动监视任务。"""
        # 参数校验
        self.logger.debug(f"MonitorTab.start_monitoring: self.model.selected_cid={self.model.selected_cid}, type={type(self.model.selected_cid)}")
        cid = self.model.selected_cid
        xml_path = self.model.danmaku_xml_path.get()
        local_danmakus_list = self.model.parsed_local_danmakus  # 获取预先解析好的本地弹幕列表，如果存在的话
        
        # 统一检查是否有CID，以及是否有本地弹幕来源（要么有xml_path，要么有local_danmakus_list）
        if not cid:
            Messagebox.show_warning("请先在“弹幕发射器”标签页加载视频。", title="CID缺失", parent=self.app)
            self.logger.warning("CID缺失，无法开始监控。") 
            return
        if not xml_path and not local_danmakus_list:
            Messagebox.show_warning("请先在“弹幕发射器”标签页选择弹幕文件或确认已解析本地弹幕。", title="弹幕数据缺失", parent=self.app)
            self.logger.warning("弹幕数据缺失，无法开始监控。")
            return
        
        try:
            interval = int(self.model.monitor_interval.get())
            tolerance = int(self.model.time_tolerance.get())
            if interval <= 0 or tolerance < 0: raise ValueError
        except ValueError:
            Messagebox.show_error("检查间隔必须为正整数，时间容差必须为非负整数。", title="设置无效", parent=self.app)
            self.logger.error("监控设置参数无效。")
            return

        self._set_ui_for_task_start()  # 更新UI状态
        
        # 启动后台线程
        self.stop_monitor_event.clear()
        self.monitor_thread = threading.Thread(
            target=self._monitor_task,
            args=(cid, xml_path, local_danmakus_list, interval, tolerance),
            daemon=True
        )
        self.monitor_thread.start()

    def stop_monitoring(self):
        """停止监视任务。"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.logger.info("正在发送停止信号...")
            self.stop_monitor_event.set()
            self.model.monitor_status_text.set("监视器：正在停止...")

    def _monitor_task(self, cid: int, xml_path: str, local_danmakus_list: list, interval: int, tolerance: int):
        """在后台线程中运行的监视核心逻辑。"""
        monitor = BiliDanmakuMonitor(cid, xml_path, local_danmakus_list, interval, tolerance)
        
        def progress_updater(matched_count, total_count):
            if total_count > 0:
                progress = (matched_count / total_count) * 100
                status = f"监视器: 运行中... ({matched_count}/{total_count})"
                self.app.after(0, lambda: (self.model.monitor_progress_var.set(progress), self.model.monitor_status_text.set(status)))
            else: # 如果总数为0，进度条也应该为0并显示对应的状态
                self.app.after(0, lambda: (self.model.monitor_progress_var.set(0), self.model.monitor_status_text.set("监视器：无弹幕可匹配")))

        monitor.run(self.stop_monitor_event, progress_updater)
        
        self.app.after(0, self._reset_ui_after_task)
        
    def _set_ui_for_task_start(self):
        """任务开始时更新UI状态。"""
        self.set_ui_state(False)
        self.start_button.config(text="停止监视", style="danger.TButton")
        self.model.monitor_status_text.set("监视器：启动中...")
        self.model.monitor_progress_var.set(0)  # 重置进度条
        # 日志清理和初始日志记录
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.config(state='disabled')

    def _reset_ui_after_task(self):
        """任务结束后（正常完成或被停止），重置UI组件状态。"""
        self.set_ui_state(True)
        self.start_button.config(text="开始监视", style="success.TButton")
        self.model.monitor_status_text.set("监视器：已停止")
