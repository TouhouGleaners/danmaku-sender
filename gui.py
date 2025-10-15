import logging
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.tooltip import ToolTip
from tkinter import filedialog, scrolledtext
import threading
from pathlib import Path

from main import BiliDanmakuSender
from config_manager import load_config, save_config


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
        self.title("B站弹幕补档工具 v0.7.1")
        self.geometry("750x700")

        self.stop_event = threading.Event()
        
        self.full_file_path = "" 
        self.part_var = ttk.StringVar()
        self.display_parts = []
        self.parts_loaded = False  # 状态标志

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1) 

        self.create_widgets()
        self.create_menu()
        self.setup_logging()
        self.load_and_populate_config()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        """创建并布局窗口中的所有UI控件"""

        # --- 身份凭证输入区 ---
        auth_frame = ttk.Labelframe(self, text="身份凭证 (Cookie)", padding=15)
        auth_frame.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        auth_frame.columnconfigure(1, weight=1)

        ttk.Label(auth_frame, text="SESSDATA:").grid(row=0, column=0, sticky="w", padx=5, pady=8)
        self.sessdata_entry = ttk.Entry(auth_frame, show="*")
        self.sessdata_entry.grid(row=0, column=1, sticky="ew")

        ttk.Label(auth_frame, text="BILI_JCT:").grid(row=1, column=0, sticky="w",padx=5, pady=8)
        self.bili_jct_entry = ttk.Entry(auth_frame, show="*")
        self.bili_jct_entry.grid(row=1, column=1, sticky="ew")
        
        # --- 设置区 ---
        settings_frame = ttk.Labelframe(self, text="参数设置", padding=15)
        settings_frame.grid(row=1, column=0, padx=10, pady=(10, 5), sticky="ew")
        settings_frame.columnconfigure(1, weight=1)

        ttk.Label(settings_frame, text="BV号:").grid(row=0, column=0, sticky="w", padx=5, pady=8)
        self.bvid_entry = ttk.Entry(settings_frame)
        self.bvid_entry.grid(row=0, column=1, columnspan=2, sticky="ew")
        self.get_parts_button = ttk.Button(settings_frame, text="获取分P", command=self.fetch_video_parts)
        self.get_parts_button.grid(row=0, column=2)

        ttk.Label(settings_frame, text="选择分P:").grid(row=1, column=0, sticky="w", padx=5, pady=8)
        self.part_combobox = ttk.Combobox(settings_frame, textvariable=self.part_var, state="readonly", bootstyle="secondary")
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
        self.min_delay_entry = ttk.Entry(advanced_frame, width=10)
        self.min_delay_entry.grid(row=0, column=1)

        ttk.Label(advanced_frame, text="最大延迟(秒):").grid(row=0, column=2, sticky="w", padx=(20, 5), pady=5)
        self.max_delay_entry = ttk.Entry(advanced_frame, width=10)
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
        self.start_button = ttk.Button(action_frame, text="开始任务", command=self.start_task, style="success.TButton", width=12)
        self.start_button.grid(row=0, column=1)

    def load_and_populate_config(self):
        """加载配置并填充到UI控件中。"""
        credentials = load_config()
        
        self.sessdata_entry.insert(0, credentials.get('SESSDATA', ''))
        self.bili_jct_entry.insert(0, credentials.get('BILI_JCT', ''))
        
        self.bvid_entry.insert(0, '')
        self.min_delay_entry.insert(0, '5.0')
        self.max_delay_entry.insert(0, '10.0')
        
        self.full_file_path = ""
        self.file_path_label.config(text="请选择弹幕XML文件...")
        self.file_path_tooltip.text = "" 

    def on_closing(self):
        """窗口关闭时被调用，只收集并保存凭证信息。"""
        credentials_to_save = {
            'SESSDATA': self.sessdata_entry.get(),
            'BILI_JCT': self.bili_jct_entry.get()
        }
        save_config(credentials_to_save)
        self.destroy()

    def select_file(self):
        """打开文件选择对话框，让用户选择弹幕XML文件。"""
        self.focus()  # 移除按钮焦点
        file_path_str = filedialog.askopenfilename(
            title="选择弹幕XML文件", filetypes=(("XML files", "*.xml"), ("All files", "*.*"))
        )
        if file_path_str:
            file_path = Path(file_path_str)
            self.full_file_path = str(file_path)
            self.file_path_label.config(text=file_path.name)
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

    def fetch_video_parts(self):
        """获取并填充视频分P列表"""
        self.focus()  # 移除按钮焦点
        bvid = self.bvid_entry.get().strip()
        sessdata = self.sessdata_entry.get().strip()
        bili_jct = self.bili_jct_entry.get().strip()
        if not all([bvid, sessdata, bili_jct]):
            logging.error("❌【输入错误】请确保 BV号、SESSDATA 和 BILI_JCT 均已填写！")
            return
        logging.info(f"正在获取 {bvid} 的分P列表...")
        self.get_parts_button.config(state='disabled')
        self.part_var.set('正在获取中...')
        self.part_combobox.config(state="disabled")

        threading.Thread(target=self._fetch_parts_worker, args=(bvid, sessdata, bili_jct), daemon=True).start()
    
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

    def _fetch_parts_worker(self, bvid, sessdata, bili_jct):
        """在工作线程中执行API调用"""
        try:
            sender = BiliDanmakuSender(sessdata, bili_jct, bvid)
            video_info = sender.get_video_info()
            self.video_pages = video_info['pages']
            
            # 创建用于显示的列表
            self.display_parts = [f"P{p['page']} - {p['part']}" for p in self.video_pages]

            def _update_ui_success():
                if self.display_parts:
                    logging.info(f"✅ 成功获取到 {len(self.display_parts)} 个分P，已为您选中第一个")
                    self.part_combobox['values'] = self.display_parts
                    self.part_var.set(self.display_parts[0])
                    self.part_combobox.config(state="readonly")
                    self.parts_loaded = True  # 成功加载后，设置标志为 True
                else:
                    self.part_combobox['values'] = []
                    self.part_var.set("未找到任何分P" if self.video_pages is not None else "获取失败")
                    self.parts_loaded = False  # 没有分P，也算加载失败
                
                self.get_parts_button.config(state='normal')
            self.after(0, _update_ui_success)
        except Exception as e:
            logging.error(f"❌ 获取分P失败: {e}")
            def _update_ui_fail():
                self.get_parts_button.config(state="normal")
                self.part_var.set("获取失败, 请检查BV号")
                self.part_combobox['values'] = []
                self.part_combobox.config(state="disabled")  # 保持禁用状态
                self.parts_loaded = False  # 失败后，明确设置标志为 False
            self.after(0, _update_ui_fail)

    def task_wrapper(self, bvid, xml_path, sessdata, bili_jct, min_delay, max_delay, cid, stop_event):
        """在单独的线程中执行弹幕发送任务的包裹函数。"""
        try:
            sender = BiliDanmakuSender(sessdata, bili_jct, bvid)
            sender.send_danmaku_from_xml(cid, xml_path, min_delay, max_delay, stop_event)
        except Exception as e:
            logging.error(f"【程序崩溃】发生未捕获的严重错误: {e}")
        finally:
            self.after(0, self._restore_ui)

    def _restore_ui(self):
        """恢复UI状态。"""
        self.start_button.config(state='normal', text="开始任务", command=self.start_task, style="success.TButton")
        self.select_button.config(state='normal')
        self.get_parts_button.config(state='normal')
        self.progress_bar.stop()
        self.progress_bar.config(mode='determinate')
        self.progress_bar['value'] = 0

    def stop_task(self):
        """设置停止事件，更新UI"""
        logging.info("ℹ️ 用户请求停止任务，将在当前弹幕发送完毕后终止...")
        self.stop_event.set()
        self.start_button.config(state='disabled', text="正在停止")

    def start_task(self):
        """点击“开始任务”按钮时的主函数。"""
        self.focus()  # 移除按钮焦点
        bvid = self.bvid_entry.get().strip()
        sessdata = self.sessdata_entry.get().strip()
        bili_jct = self.bili_jct_entry.get().strip()
        
        try:
            min_delay = float(self.min_delay_entry.get())
            max_delay = float(self.max_delay_entry.get())
            if min_delay < 0 or max_delay < 0 or min_delay > max_delay:
                raise ValueError("延迟时间必须为正数，且最小延迟不大于最大延迟")
        except (ValueError, TypeError):
            logging.error("❌【输入错误】延迟时间设置不合法！")
            return

        if not all([bvid, self.full_file_path, sessdata, bili_jct]):
            logging.error("❌【输入错误】请确保 BV号、弹幕文件、SESSDATA 和 BILI_JCT 都已填写！")
            return
        
        if not self.parts_loaded:
            logging.error("❌【操作错误】请先成功获取并选择一个分P！")
            return
        
        selected_part_str = self.part_var.get()

        try:
            # 通过显示文本，在self.display_parts中反查出索引
            selected_index = self.display_parts.index(selected_part_str)
        except ValueError:
            logging.error("❌【程序错误】选择的分P与列表不匹配，请重新获取分P")
            return
        
        selected_cid = self.video_pages[selected_index]['cid']
        logging.info(f"已选择目标分P: {selected_part_str}, CID: {selected_cid}")

        self.stop_event.clear()  # 每次开始新任务前，清除旧的停止信号
        self.start_button.config(text="紧急停止", command=self.stop_task, style="danger.TButton")
        self.select_button.config(state='disabled')
        self.get_parts_button.config(state='disabled')
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', ttk.END)
        self.log_text.config(state='disabled')
        self.progress_bar.config(mode='indeterminate')
        self.progress_bar.start()

        try:
            thread = threading.Thread(
                target=self.task_wrapper, 
                args=(bvid, self.full_file_path, sessdata, bili_jct, min_delay, max_delay, selected_cid, self.stop_event),
                daemon=True
            )
            thread.start()
        except Exception as e:
            logging.error(f"【程序崩溃】无法启动后台任务线程: {e}")
            self._restore_ui()  # 同时恢复UI状态，因为任务没有开始


if __name__ == "__main__":
    app = Application()
    app.mainloop()

