import logging
import threading
import time
from tkinter import scrolledtext
from datetime import timedelta
import ttkbootstrap as ttk
from ttkbootstrap.tooltip import ToolTip 


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
            app: 主应用实例，用于作为Messagebox等对话框的父窗口（尽管目前无Messagebox）。
        """
        super().__init__(parent, padding=15)
        self.model = model
        self.app = app
        
        # 配置主Frame的列和行权重，确保内容区域随窗口调整大小
        self.columnconfigure(0, weight=1) # 使内容区（唯一列）随窗口水平拉伸
        self.rowconfigure(2, weight=1)    # 使日志区（row 2）随窗口垂直拉伸
                                          # row 0, 1, 3 保持固定高度

        self.monitor_thread = None         # 监视任务的线程实例
        self.stop_monitor_event = threading.Event() # 用于控制监视线程停止的事件
        
        # 绑定来自共享数据模型的变量，以便UI组件自动响应数据变化
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
        monitor_settings_frame = ttk.Labelframe(self, text="监视设置", padding=15, bootstyle="primary")
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
        self.interval_entry = ttk.Entry(advanced_settings_frame, width=10, textvariable=self.model.monitor_interval)
        self.interval_entry.grid(row=0, column=1, sticky="w", padx=(0,10))

        # 时间容差设置
        ttk.Label(advanced_settings_frame, text="时间容差(ms):").grid(row=0, column=2, sticky="w", padx=5, pady=8)
        self.tolerance_entry = ttk.Entry(advanced_settings_frame, width=10, textvariable=self.model.time_tolerance)
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
        self.progress_bar = ttk.Progressbar(control_bar_frame, mode='determinate', style='success.Striped.TProgressbar')
        self.progress_bar.grid(row=0, column=1, sticky="ew", padx=(10, 10)) # 左右各有10像素间距

        # 开始/停止监视按钮：控制监视任务的启动/停止
        self.start_button = ttk.Button(
            control_bar_frame, 
            text="开始监视", 
            command=self.start_monitoring,
            style="primary.TButton", 
            width=12
        )
        self.start_button.grid(row=0, column=2, sticky="e")

    def log(self, message):
        """
        向GUI的日志文本框和控制台输出信息。
        TODO: 实现向 self.log_text 写入日志的功能。
        """
        print(message)
    
    def start_monitoring(self):
        """
        启动或停止监视任务的占位符方法。
        根据当前状态切换按钮文本和样式，并更新本地状态标签。
        TODO: 在此方法中实现实际的监视任务启动/停止逻辑。
        """
        current_status = self.model.monitor_status_text.get()
        if "运行中" in current_status:
            self.model.monitor_status_text.set("监视器：已停止")
            self.log("【占位符】“停止监视”按钮被点击了！")
            self.start_button.config(text="开始监视", style="primary.TButton")
        else:
            self.model.monitor_status_text.set("监视器：运行中...")
            self.log("【占位符】“开始监视”按钮被点击了！")
            self.start_button.config(text="停止监视", style="danger.TButton")

