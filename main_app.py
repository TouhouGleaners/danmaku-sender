import logging
import ttkbootstrap as ttk
from ttkbootstrap.constants import *

from config_manager import load_config, save_config
from shared_data import SharedDataModel
from sender_tab import SenderTab
from monitor_tab import MonitorTab


class GuiLoggingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.sender_log_callable = None
        self.monitor_log_callable = None

    def emit(self, record):
        msg = self.format(record)
        # TODO: 未来可以根据日志来源决定输出到哪个tab
        # 目前所有日志都来自发射器，所以直接输出到发射器日志
        if self.sender_log_callable:
            self.sender_log_callable(msg)

class Application(ttk.Window):
    def __init__(self):
        super().__init__(themename="litera")
        self.title("B站弹幕发射器 v0.8.4")
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
        """配置logging，将日志输出到GUI的文本框中"""
        self.gui_handler = GuiLoggingHandler()
        # 将发射器tab的日志更新方法注册到handler
        log_widget = getattr(self.sender_tab_frame, 'log_text', None)
        if log_widget:
            self.gui_handler.sender_log_callable = self.log_to_gui_widget(log_widget)
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
        self.gui_handler.setFormatter(formatter)
        logger.addHandler(self.gui_handler)

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
        ttk.Label(frame, text="版本: 0.8.4").pack(pady=5)
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