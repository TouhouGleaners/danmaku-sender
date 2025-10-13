import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.tooltip import ToolTip
from tkinter import filedialog, scrolledtext
import threading
from pathlib import Path

from main import BiliDanmakuSender
from config_manager import load_config, save_config

class Application(ttk.Window):
    def __init__(self):
        super().__init__(themename="litera")
        self.title("B站弹幕补档工具 v0.3.0")
        self.geometry("750x700")
        
        self.full_file_path = "" 

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1) 

        self.create_widgets()
        self.load_and_populate_config()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        """创建并布局窗口中的所有UI控件"""
        
        # --- 设置区 ---
        settings_frame = ttk.Labelframe(self, text="参数设置", padding=15)
        settings_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        settings_frame.columnconfigure(1, weight=1)

        ttk.Label(settings_frame, text="BV号:").grid(row=0, column=0, sticky="w", padx=5, pady=8)
        self.bvid_entry = ttk.Entry(settings_frame)
        self.bvid_entry.grid(row=0, column=1, columnspan=2, sticky="ew")

        ttk.Label(settings_frame, text="选择分P:").grid(row=1, column=0, sticky="w", padx=5, pady=8)
        self.part_combobox = ttk.Combobox(settings_frame, state="disabled")
        self.part_combobox.grid(row=1, column=1, sticky="ew", padx=(0, 5))
        self.get_parts_button = ttk.Button(settings_frame, text="获取分P", command=self.fetch_video_parts)
        self.get_parts_button.grid(row=0, column=2)

        ttk.Label(settings_frame, text="弹幕文件:").grid(row=2, column=0, sticky="w", padx=5, pady=8)
        self.file_path_label = ttk.Label(settings_frame, text="请选择弹幕XML文件...", style="secondary.TLabel")
        self.file_path_label.grid(row=2, column=1, sticky="ew", padx=(0, 5))
        self.select_button = ttk.Button(settings_frame, text="选择文件", command=self.select_file, style="info.TButton")
        self.select_button.grid(row=2, column=2, sticky="e")
        self.file_path_tooltip = ToolTip(self.file_path_label, text="") 

        # --- 身份凭证输入区 ---
        auth_frame = ttk.Labelframe(self, text="身份凭证 (Cookie)", padding=15)
        auth_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        auth_frame.columnconfigure(1, weight=1)
        ttk.Label(auth_frame, text="SESSDATA:").grid(row=0, column=0, sticky="w", padx=5, pady=8)
        self.sessdata_entry = ttk.Entry(auth_frame, show="*")
        self.sessdata_entry.grid(row=0, column=1, sticky="ew")
        ttk.Label(auth_frame, text="BILI_JCT:").grid(row=1, column=0, sticky="w",padx=5, pady=8)
        self.bili_jct_entry = ttk.Entry(auth_frame, show="*")
        self.bili_jct_entry.grid(row=1, column=1, sticky="ew")
        
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
        config = load_config()
        
        self.sessdata_entry.insert(0, config.get('SESSDATA', ''))
        self.bili_jct_entry.insert(0, config.get('BILI_JCT', ''))
        
        self.bvid_entry.insert(0, '')
        self.min_delay_entry.insert(0, str(config.get('MIN_DELAY', '5.0')))
        self.max_delay_entry.insert(0, str(config.get('MAX_DELAY', '10.0')))
        
        self.full_file_path = ""
        self.file_path_label.config(text="请选择弹幕XML文件...")
        self.file_path_tooltip.text = "" 

    def on_closing(self):
        """窗口关闭时被调用，只收集并保存凭证信息。"""
        credentials_to_save = {'SESSDATA': self.sessdata_entry.get(), 'BILI_JCT': self.bili_jct_entry.get()}
        save_config(credentials_to_save)
        self.destroy()

    def select_file(self):
        """打开文件选择对话框，让用户选择弹幕XML文件。"""
        file_path_str = filedialog.askopenfilename(
            title="选择弹幕XML文件", filetypes=(("XML files", "*.xml"), ("All files", "*.*"))
        )
        if file_path_str:
            file_path = Path(file_path_str)
            self.full_file_path = str(file_path)
            self.file_path_label.config(text=file_path.name)
            self.file_path_tooltip.text = str(file_path)

    def fetch_video_parts(self):
        """获取并填充视频分P列表"""
        bvid = self.bvid_entry.get().strip()
        sessdata = self.sessdata_entry.get().strip()
        bili_jct = self.bili_jct_entry.get().strip()
        if not all([bvid, sessdata, bili_jct]):
            self.log_to_gui("❌【输入错误】请确保 BV号、SESSDATA 和 BILI_JCT 均已填写！")
            return
        self.log_to_gui(f"正在获取 {bvid} 的分P列表...")
        self.get_parts_button.config(state='disabled')
        self.part_combobox.set('')  # 清空
        self.part_combobox.config(state="disabled")

        threading.Thread(target=self._fetch_parts_worker, args=(bvid, sessdata, bili_jct), daemon=True).start()
    
    def _fetch_parts_worker(self, bvid, sessdata, bili_jct):
        """在工作线程中执行API调用"""
        try:
            sender = BiliDanmakuSender(sessdata, bili_jct, bvid)
            sender.log = self.log_to_gui
            video_info = sender.get_video_info()
            self.video_pages = video_info['pages']
            
            # 创建用于显示的列表
            display_parts = [f"P{p['page']} - {p['part']}" for p in self.video_pages]

            def _update_ui_success():
                self.part_combobox['values'] = display_parts
                if len(display_parts) > 1:
                    self.log_to_gui(f"✅ 成功获取到 {len(display_parts)} 个分P，请在下拉框中选择。")
                    self.part_combobox.current(0) # 默认选中第一个
                    self.part_combobox.config(state="readonly")
                else:
                    self.log_to_gui("✅ 这是一个单P视频，已自动为您选中。")
                    self.part_combobox.current(0)
                    self.part_combobox.config(state="readonly")
                self.get_parts_button.config(state='normal')
            self.after(0, _update_ui_success)
        except Exception as e:
            self.log_to_gui(f"❌ 获取分P失败: {e}")
            def _update_ui_fail():
                self.get_parts_button.config(state="normal")
            self.after(0, _update_ui_fail)

    def log_to_gui(self, message):
        """将消息安全地发送到GUI的日志区域（线程安全）"""
        def _update():
            self.log_text.config(state='normal')
            self.log_text.insert(ttk.END, str(message) + '\n')
            self.log_text.see(ttk.END)
            self.log_text.config(state='disabled')
        self.after(0, _update)

    def task_wrapper(self, bvid, xml_path, sessdata, bili_jct, min_delay, max_delay, cid):
        """在单独的线程中执行弹幕发送任务的包裹函数。"""
        try:
            sender = BiliDanmakuSender(sessdata, bili_jct, bvid)
            sender.log = self.log_to_gui
            sender.send_danmaku_from_xml(cid, xml_path, min_delay, max_delay)
        except Exception as e:
            self.log_to_gui(f"【程序崩溃】发生未捕获的严重错误: {e}")
        finally:
            def _restore_ui():
                self.start_button.config(state='normal', text="开始任务")
                self.select_button.config(state='normal')
                self.progress_bar.stop()
                self.progress_bar.config(mode='determinate')
                self.progress_bar['value'] = 0
            self.after(0, _restore_ui)

    def start_task(self):
        """点击“开始任务”按钮时的主函数。"""
        bvid = self.bvid_entry.get().strip()
        sessdata = self.sessdata_entry.get().strip()
        bili_jct = self.bili_jct_entry.get().strip()
        
        try:
            min_delay = float(self.min_delay_entry.get())
            max_delay = float(self.max_delay_entry.get())
            if min_delay < 0 or max_delay < 0 or min_delay > max_delay:
                raise ValueError("延迟时间必须为正数，且最小延迟不大于最大延迟")
        except (ValueError, TypeError):
            self.log_to_gui("❌【输入错误】延迟时间设置不合法！")
            return

        if not all([bvid, self.full_file_path, sessdata, bili_jct]):
            self.log_to_gui("❌【输入错误】请确保 BV号、弹幕文件、SESSDATA 和 BILI_JCT 都已填写！")
            return
        
        if not hasattr(self, 'video_pages') or not self.video_pages:
            self.log_to_gui("❌【操作错误】请先点击“获取分P”并选择一个分P！")
            return
        
        selected_index = self.part_combobox.current()
        if selected_index == -1: # 用户没有选择任何项
            self.log_to_gui("❌【操作错误】请选择一个有效的分P！")
            return
        
        selected_cid = self.video_pages[selected_index]['cid']
        self.log_to_gui(f"已选择目标分P: {self.part_combobox.get()}, CID: {selected_cid}")

        self.start_button.config(state='disabled', text="正在运行...")
        self.select_button.config(state='disabled')
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', ttk.END)
        self.log_text.config(state='disabled')
        self.progress_bar.config(mode='indeterminate')
        self.progress_bar.start()

        try:
            thread = threading.Thread(
                target=self.task_wrapper, 
                args=(bvid, self.full_file_path, sessdata, bili_jct, min_delay, max_delay, selected_cid),
                daemon=True
            )
            thread.start()
        except Exception as e:
            self.log_to_gui(f"【程序崩溃】无法启动后台任务线程: {e}")
            # 同时恢复UI状态，因为任务没有开始
            self.start_button.config(state='normal', text="开始任务")
            self.select_button.config(state='normal')
            self.progress_bar.stop()


if __name__ == "__main__":
    app = Application()
    app.mainloop()

