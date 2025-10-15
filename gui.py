import logging
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.tooltip import ToolTip
from tkinter import filedialog, scrolledtext
from pathlib import Path

from config_manager import load_config, save_config
from shared_data import SharedDataModel
from controller import AppController


class GuiLoggingHandler(logging.Handler):
    """
    一个将日志记录重定向到 Tkinter ScrolledText 控件的 Handler。
    """
    def __init__(self, text_widget_update_callable):
        super().__init__()
        # 存储一个可调用的函数，该函数用于线程安全地更新GUI
        self.text_widget_update_callable = text_widget_update_callable

    def emit(self, record):
        """
        处理一条日志记录。
        这个方法会被 logging 模块在后台线程中调用。
        """
        msg = self.format(record)
        self.text_widget_update_callable(msg)


class Application(ttk.Window):
    def __init__(self):
        super().__init__(themename="litera")
        self.title("B站弹幕补档工具 v0.8.3")
        self.geometry("750x700")

        # --- 模型、控制器、视图的装配 ---
        self.shared_data = SharedDataModel()
        self.controller = AppController(self.shared_data, self)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1) 

        self.create_widgets()
        self.create_menu()
        self.setup_logging()
        self.load_and_populate_config()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        """创建并布局窗口中的所有UI控件，并将命令绑定到控制器"""

        # --- 身份凭证输入区 ---
        auth_frame = ttk.Labelframe(self, text="身份凭证 (Cookie)", padding=15)
        auth_frame.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        auth_frame.columnconfigure(1, weight=1)

        ttk.Label(auth_frame, text="SESSDATA:").grid(row=0, column=0, sticky="w", padx=5, pady=8)
        self.sessdata_entry = ttk.Entry(auth_frame, show="*", textvariable=self.shared_data.sessdata)
        self.sessdata_entry.grid(row=0, column=1, sticky="ew")

        ttk.Label(auth_frame, text="BILI_JCT:").grid(row=1, column=0, sticky="w",padx=5, pady=8)
        self.bili_jct_entry = ttk.Entry(auth_frame, show="*", textvariable=self.shared_data.bili_jct)
        self.bili_jct_entry.grid(row=1, column=1, sticky="ew")
        
        # --- 设置区 ---
        settings_frame = ttk.Labelframe(self, text="参数设置", padding=15)
        settings_frame.grid(row=1, column=0, padx=10, pady=(10, 5), sticky="ew")
        settings_frame.columnconfigure(1, weight=1)

        ttk.Label(settings_frame, text="BV号:").grid(row=0, column=0, sticky="w", padx=5, pady=8)
        self.bvid_entry = ttk.Entry(settings_frame, textvariable=self.shared_data.bvid)
        self.bvid_entry.grid(row=0, column=1, columnspan=2, sticky="ew")
        # <-- 3. 将按钮命令指向控制器的方法
        self.get_parts_button = ttk.Button(settings_frame, text="获取分P", command=self.controller.fetch_video_parts)
        self.get_parts_button.grid(row=0, column=2)

        ttk.Label(settings_frame, text="选择分P:").grid(row=1, column=0, sticky="w", padx=5, pady=8)
        self.part_combobox = ttk.Combobox(settings_frame, textvariable=self.shared_data.part_var, state="readonly", bootstyle="secondary")
        self.part_combobox.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 5))
        self.part_combobox.bind("<<ComboboxSelected>>", lambda _: (self.focus(), self.part_combobox.selection_clear()))
        self.part_combobox.set("请先获取分P")
        self.part_combobox.config(state="disabled")

        ttk.Label(settings_frame, text="弹幕文件:").grid(row=2, column=0, sticky="w", padx=5, pady=8)
        self.file_path_label = ttk.Label(settings_frame, text="请选择弹幕XML文件...", style="secondary.TLabel")
        self.file_path_label.grid(row=2, column=1, sticky="ew", padx=(0, 5))
        self.select_button = ttk.Button(settings_frame, text="选择文件", command=self.select_file, style="info.TButton")
        self.select_button.grid(row=2, column=2, sticky="e")
        self.file_path_tooltip = ToolTip(self.file_path_label, text="") 
        
        # --- 高级设置 (延迟) ---
        advanced_frame = ttk.Labelframe(self, text="高级设置", padding=15)
        advanced_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        advanced_frame.columnconfigure(1, weight=1); advanced_frame.columnconfigure(3, weight=1)

        ttk.Label(advanced_frame, text="最小延迟(秒):").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.min_delay_entry = ttk.Entry(advanced_frame, width=10, textvariable=self.shared_data.min_delay)
        self.min_delay_entry.grid(row=0, column=1)

        ttk.Label(advanced_frame, text="最大延迟(秒):").grid(row=0, column=2, sticky="w", padx=(20, 5), pady=5)
        self.max_delay_entry = ttk.Entry(advanced_frame, width=10, textvariable=self.shared_data.max_delay)
        self.max_delay_entry.grid(row=0, column=3)
        
        # --- 日志输出区 ---
        log_frame = ttk.Labelframe(self, text="运行日志", padding=10)
        log_frame.grid(row=3, column=0, padx=10, pady=5, sticky="nsew") 
        log_frame.columnconfigure(0, weight=1); log_frame.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=ttk.WORD, state='disabled', font=("TkDefaultFont", 9))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        
        # --- 操作区 ---
        action_frame = ttk.Frame(self, padding=(15, 10))
        action_frame.grid(row=4, column=0, padx=10, pady=10, sticky="ew")
        action_frame.columnconfigure(0, weight=1)
        self.progress_bar = ttk.Progressbar(action_frame, mode='determinate', style='success.Striped.TProgressbar')
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        # <-- 4. 将按钮命令指向控制器的方法
        self.start_button = ttk.Button(action_frame, text="开始任务", command=self.controller.start_task, style="success.TButton", width=12)
        self.start_button.grid(row=0, column=1)

    def load_and_populate_config(self):
        """加载配置并填充到UI控件中。"""
        credentials = load_config()
        self.shared_data.sessdata.set(credentials.get('SESSDATA', ''))
        self.shared_data.bili_jct.set(credentials.get('BILI_JCT', ''))
        self.shared_data.bvid.set('')
        self.shared_data.danmaku_xml_path.set("")
        self.file_path_label.config(text="请选择弹幕XML文件...")
        self.file_path_tooltip.text = "" 

    def on_closing(self):
        """窗口关闭时被调用，只收集并保存凭证信息。"""
        credentials_to_save = {
            'SESSDATA': self.shared_data.sessdata.get(),
            'BILI_JCT': self.shared_data.bili_jct.get()
        }
        save_config(credentials_to_save)
        self.destroy()

    def select_file(self):
        """打开文件选择对话框，让用户选择弹幕XML文件。"""
        self.focus()
        file_path_str = filedialog.askopenfilename(
            title="选择弹幕XML文件", filetypes=(("XML files", "*.xml"), ("All files", "*.*"))
        )
        if file_path_str:
            file_path = Path(file_path_str)
            self.shared_data.danmaku_xml_path.set(str(file_path))
            self.file_path_tooltip.text = str(file_path)
    
    def setup_logging(self):
        """配置logging，将日志输出到GUI的文本框中"""
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)

        gui_handler = GuiLoggingHandler(self.log_to_gui)

        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        gui_handler.setFormatter(formatter)
        logger.addHandler(gui_handler)

    def log_to_gui(self, message):
        """将消息安全地发送到GUI的日志区域（线程安全）"""
        def _update():
            self.log_text.config(state='normal')
            self.log_text.insert(ttk.END, str(message) + '\n')
            self.log_text.see(ttk.END)
            self.log_text.config(state='disabled')
        self.after(0, _update)

    def create_menu(self):
        """创建顶部菜单栏"""
        menu_bar = ttk.Menu(self)
        self.config(menu=menu_bar)

        # --- 文件菜单 ---
        file_menu = ttk.Menu(menu_bar, tearoff=0)
        menu_bar.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="退出", command=self.on_closing)

        # --- 帮助菜单 ---
        help_menu = ttk.Menu(menu_bar, tearoff=0)
        menu_bar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="使用说明", command=self.show_help_window)
        help_menu.add_separator()
        help_menu.add_command(label="关于", command=self.show_about_window)

    def show_help_window(self):
        """显示使用说明窗口"""
        help_win = ttk.Toplevel(self)
        help_win.title("使用说明")
        help_win.transient(self)
        help_win.grab_set()

        frame = ttk.Frame(help_win, padding=20)
        frame.pack(fill=BOTH, expand=True)
        help_text = """
        要获取 SESSDATA 和 BILI_JCT，请按以下步骤操作：
        1. 在你的浏览器（推荐Chrome/Edge）中登录Bilibili。
        2. 访问B站任意一个页面，比如主页 www.bilibili.com。
        3. 按 F12 打开“开发者工具”。
        4. 切换到 "Application" (应用程序) 标签页。
        5. 在左侧菜单中，找到 "Storage" (存储) -> "Cookies" -> "https://www.bilibili.com"。
        6. 在右侧的列表中找到以下两项，并复制它们 "Value" (值) 列的内容：
           - SESSDATA
           - bili_jct
        7. 将复制的内容粘贴到本工具对应的输入框中即可。
        """

        ttk.Label(frame, text="使用说明", font=("TkDefaultFont", 14, "bold")).pack(pady=(0, 15))
        ttk.Label(frame, text=help_text, justify=LEFT).pack(pady=5)

        # 让窗口大小自适应内容
        help_win.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - (help_win.winfo_width() // 2)
        y = self.winfo_y() + (self.winfo_height() // 2) - (help_win.winfo_height() // 2)
        help_win.geometry(f"+{x}+{y}")  # 窗口居中于主窗口
        help_win.focus_force()
        help_win.wait_window()

    def show_about_window(self):
        """显示关于窗口"""
        about_win = ttk.Toplevel(self)
        about_win.title("关于")
        about_win.transient(self)
        about_win.grab_set()
        about_win.resizable(False, False)

        frame = ttk.Frame(about_win, padding=20)
        frame.pack(fill=BOTH, expand=True)

        ttk.Label(frame, text="B站弹幕补档工具", font=("TkDefaultFont", 14, "bold")).pack(pady=(0, 10))
        ttk.Label(frame, text="版本: 0.7.1").pack(pady=5)
        ttk.Label(frame, text="作者: Miku_oso").pack(pady=5)

        # 让窗口大小自适应内容
        about_win.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - (about_win.winfo_width() // 2)
        y = self.winfo_y() + (self.winfo_height() // 2) - (about_win.winfo_height() // 2)
        about_win.geometry(f"+{x}+{y}")  # 窗口居中于主窗口
        about_win.focus_force()
        about_win.wait_window()


if __name__ == "__main__":
    app = Application()
    app.mainloop()

