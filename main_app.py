import logging
import ttkbootstrap as ttk
from ttkbootstrap.constants import *

from config_manager import load_config, save_config
from shared_data import SharedDataModel
from sender_tab import SenderTab
from monitor_tab import MonitorTab


class GuiLoggingHandler(logging.Handler):
    """
    一个自定义的日志处理程序，将日志消息根据其来源路由到不同的GUI文本框。
    它通过检查日志记录的名称(record.name)来决定目标。
    """
    def __init__(self):
        super().__init__()
        # 存储不同日志目标的更新函数
        self.output_targets = {
            "sender_tab": None,
            "monitor_tab": None,
        }

    def emit(self, record):
        """根据 record.name 将日志消息发送到正确的GUI组件。"""
        msg = self.format(record)
        
        # 精确路由
        if record.name == "sender_tab" and self.output_targets["sender_tab"]:
            self.output_targets["sender_tab"](msg)
        elif record.name == "monitor_tab" and self.output_targets["monitor_tab"]:
            self.output_targets["monitor_tab"](msg)
        # 关联路由: BiliDanmakuSender 的日志也应显示在发射器标签页
        elif record.name == "BiliDanmakuSender" and self.output_targets["sender_tab"]:
            self.output_targets["sender_tab"](msg)
        # 备用 (Fallback) 路由: 对于未知来源的日志，默认输出到发射器日志框
        else:
            if self.output_targets["sender_tab"]:
                # 为了区分，给这些通用日志加上来源名称作为前缀
                self.output_targets["sender_tab"](f"[{record.name}] {msg}")


class Application(ttk.Window):
    def __init__(self):
        super().__init__(themename="litera")
        self.title("B站弹幕发射器 v0.9.1")
        self.geometry("780x750")
        # --- 模型、控制器、视图的装配 ---
        self.shared_data = SharedDataModel()
        
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1) 
        self.create_widgets()
        self.create_menu()
        self.setup_logging()
        self.load_and_populate_config()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        notebook = ttk.Notebook(self)
        notebook.grid(row=0, column=0, padx=10, pady=5, sticky="nsew")

        # --- 创建并添加标签页 ---
        self.sender_tab_frame = SenderTab(notebook, self.shared_data, self)
        self.monitor_tab_frame = MonitorTab(notebook, self.shared_data, self)
        notebook.add(self.sender_tab_frame, text="弹幕发射器")
        notebook.add(self.monitor_tab_frame, text="弹幕监视器")

    def load_and_populate_config(self):
        """加载配置并填充到UI控件中。"""
        credentials = load_config()
        self.shared_data.sessdata.set(credentials.get('SESSDATA', ''))
        self.shared_data.bili_jct.set(credentials.get('BILI_JCT', ''))

    def on_closing(self):
        """窗口关闭时被调用，保存凭证信息。"""
        credentials_to_save = {
            'SESSDATA': self.shared_data.sessdata.get(),
            'BILI_JCT': self.shared_data.bili_jct.get()
        }
        save_config(credentials_to_save)
        self.destroy()

    def setup_logging(self):
        """
        配置一个健壮的日志系统，能将不同模块的日志路由到对应的GUI界面。
        """
        self.gui_handler = GuiLoggingHandler()
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
        self.gui_handler.setFormatter(formatter)

        # 注册GUI输出目标
        if hasattr(self.sender_tab_frame, 'log_text'):
            self.gui_handler.output_targets["sender_tab"] = self.log_to_gui_widget(self.sender_tab_frame.log_text)
        if hasattr(self.monitor_tab_frame, 'log_text'):
            self.gui_handler.output_targets["monitor_tab"] = self.log_to_gui_widget(self.monitor_tab_frame.log_text)

        # 配置各个模块的具名Logger
        # 每个模块内部通过 logging.getLogger("模块名") 获取自己的logger实例
        loggers_to_configure = ["sender_tab", "monitor_tab", "DanmakuSender", "DanmakuParser"]
        for name in loggers_to_configure:
            logger = logging.getLogger(name)
            logger.setLevel(logging.INFO)
            logger.propagate = False  # 阻止日志向上传播到根logger，避免重复处理
            logger.addHandler(self.gui_handler)

        # 配置根Logger，用于捕获所有其他未被专门处理的日志 (例如第三方库)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        # 清理可能存在的旧handler，避免重复输出到控制台
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        root_logger.addHandler(self.gui_handler) # 让根Logger也使用我们的GUI Handler

    def log_to_gui_widget(self, text_widget):
        """返回一个用于更新特定ScrolledText控件的闭包函数"""
        def _update_log(message):
            def _task():
                text_widget.config(state='normal')
                text_widget.insert(ttk.END, str(message) + '\n')
                text_widget.see(ttk.END)
                text_widget.config(state='disabled')
            self.after(0, _task)
        return _update_log
    
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
        ttk.Label(frame, text="版本: 0.9.1").pack(pady=5)
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