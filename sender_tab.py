import logging
import threading
from tkinter import filedialog, scrolledtext
from pathlib import Path
import ttkbootstrap as ttk
from ttkbootstrap.tooltip import ToolTip

from bili_sender import BiliDanmakuSender
from bili_danmaku_utils import DanmakuParser


class SenderTab(ttk.Frame):
    def __init__(self, parent, model, app):
        """弹幕发射器标签页

        Args:
            parent: 父容器 (Notebook)
            model: 共享数据模型 (SharedDataModel)
            app: 主应用实例 (Application), 用于线程安全的UI更新
        """
        super().__init__(parent, padding=15)
        self.model = model
        self.app = app  # 主应用实例，用于after调用
        self.logger = logging.getLogger("sender_tab")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.stop_event = threading.Event()
        self.danmaku_parser = DanmakuParser()

        self._create_widgets()

    def _create_widgets(self):
        """创建并布局此标签页中的所有UI控件"""

        # --- 身份凭证输入区 ---
        auth_frame = ttk.Labelframe(self, text="身份凭证 (Cookie)", padding=15)
        auth_frame.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        auth_frame.columnconfigure(1, weight=1)

        ttk.Label(auth_frame, text="SESSDATA:").grid(row=0, column=0, sticky="w", padx=5, pady=8)
        self.sessdata_entry = ttk.Entry(auth_frame, show="*", textvariable=self.model.sessdata)
        self.sessdata_entry.grid(row=0, column=1, sticky="ew")

        ttk.Label(auth_frame, text="BILI_JCT:").grid(row=1, column=0, sticky="w",padx=5, pady=8)
        self.bili_jct_entry = ttk.Entry(auth_frame, show="*", textvariable=self.model.bili_jct)
        self.bili_jct_entry.grid(row=1, column=1, sticky="ew")

        # --- 设置区 ---
        settings_frame = ttk.Labelframe(self, text="参数设置", padding=15)
        settings_frame.grid(row=1, column=0, padx=10, pady=(10, 5), sticky="ew")
        settings_frame.columnconfigure(1, weight=1)

        ttk.Label(settings_frame, text="BV号:").grid(row=0, column=0, sticky="w", padx=5, pady=8)
        self.bvid_entry = ttk.Entry(settings_frame, textvariable=self.model.bvid)
        self.bvid_entry.grid(row=0, column=1, sticky="ew") 
        self.get_parts_button = ttk.Button(settings_frame, text="获取分P", command=self.fetch_video_parts)
        self.get_parts_button.grid(row=0, column=2, padx=(5, 0))

        ttk.Label(settings_frame, text="选择分P:").grid(row=1, column=0, sticky="w", padx=5, pady=8)
        self.part_combobox = ttk.Combobox(settings_frame, textvariable=self.model.part_var, state="readonly", bootstyle="secondary")
        self.part_combobox.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 5))
        self.part_combobox.bind("<<ComboboxSelected>>", lambda _: (self.focus(), self.part_combobox.selection_clear(), self._on_part_selected()))
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
        self.min_delay_entry = ttk.Entry(advanced_frame, width=10, textvariable=self.model.min_delay)
        self.min_delay_entry.grid(row=0, column=1)

        ttk.Label(advanced_frame, text="最大延迟(秒):").grid(row=0, column=2, sticky="w", padx=(20, 5), pady=5)
        self.max_delay_entry = ttk.Entry(advanced_frame, width=10, textvariable=self.model.max_delay)
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

    def select_file(self):
        """打开文件选择对话框，让用户选择弹幕XML文件。"""
        self.app.focus()
        file_path_str = filedialog.askopenfilename(
            title="选择弹幕XML文件", filetypes=(("XML files", "*.xml"), ("All files", "*.*"))
        )
        if not file_path_str:
            return
        file_path = Path(file_path_str)
        self.model.danmaku_xml_path.set(str(file_path))
        self.file_path_label.config(text=file_path.name)
        self.file_path_tooltip.text = str(file_path)
        self.logger.info(f"已选择文件: {file_path}")     
        self.model.parsed_local_danmakus = []  # 清空旧的解析结果

        try:
            parsed_list = self.danmaku_parser.parse_xml_file(str(file_path))
            if parsed_list:
                # 将解析成功的结果存入共享模型
                self.model.parsed_local_danmakus = parsed_list
                self.logger.info(f"✅ 文件解析成功，共 {len(parsed_list)} 条弹幕已准备就绪。")
            else:
                self.logger.warning("⚠️ 文件解析完成，但未找到有效弹幕。请检查文件内容。")
        except Exception as e:
            self.logger.error(f"❌ 文件解析失败: {e}")
            self.model.danmaku_xml_path.set("")  # 解析失败，清空路径，防止用户使用错误的文件
            self.file_path_label.config(text="解析失败，请重选")
    
    def _on_part_selected(self, event=None):
        """当用户从下拉框选择一个分P时，更新共享模型中的 selected_cid"""
        self.app.focus()
        selected_index = self.part_combobox.current()
        if selected_index != -1:
            try:
                # 关键：将选中的CID存入共享模型
                self.model.selected_cid = self.model.ordered_cids[selected_index]
                self.logger.info(f"已选择目标分P: {self.model.part_var.get()}, CID: {self.model.selected_cid}")
            except IndexError:
                self.logger.error("程序错误：选择的索引超出了CID列表范围。")
                self.model.selected_cid = None

    def fetch_video_parts(self):
        """获取视频分P列表"""
        self.app.focus()  # 移除按钮焦点

        bvid = self.model.bvid.get().strip()
        sessdata = self.model.sessdata.get().strip()
        bili_jct = self.model.bili_jct.get().strip()

        if not all([bvid, sessdata, bili_jct]):
            self.logger.error("❌【输入错误】请确保 BV号、弹幕文件、SESSDATA 和 BILI_JCT 均已填写！")
            return
        
        self.logger.info(f"正在获取 {bvid} 的分P列表...")
        self.get_parts_button.config(state='disabled')
        self.model.part_var.set('正在获取中...')
        self.part_combobox.config(state="disabled")

        threading.Thread(target=self._fetch_parts_worker, args=(bvid, sessdata, bili_jct), daemon=True).start()

    def _fetch_parts_worker(self, bvid, sessdata, bili_jct):
        """在工作线程中执行获取分P的API调用"""
        try:
            sender = BiliDanmakuSender(sessdata, bili_jct, bvid)
            video_info = sender.get_video_info()
            pages = video_info.get('pages', [])

            # 先清空模型中的旧数据
            self.model.cid_parts_map = {}
            self.model.ordered_cids = []
            display_parts = []

            # 遍历API返回结果，填充模型数据
            for p in pages:
                cid = p['cid']
                part_name = f"P{p['page']} - {p['part']}"
                self.model.cid_parts_map[cid] = part_name
                self.model.ordered_cids.append(cid)
                display_parts.append(part_name)

            def _update_ui_success():
                # 这是一个在主线程中更新UI的回调函数
                if display_parts:
                    self.logger.info(f"✅ 成功获取到 {len(display_parts)} 个分P，已为您选中第一个")
                    self.part_combobox['values'] = display_parts
                    self.model.part_var.set(display_parts[0])  # 默认选中第一个
                    self.part_combobox.config(state="readonly")
                    self._on_part_selected()
                else:
                    self.part_combobox['values'] = []
                    self.model.part_var.set("未找到任何分P")
                
                self.get_parts_button.config(state='normal')
            
            self.app.after(0, _update_ui_success)
        except Exception as e:
            self.logger.error(f"❌ 获取分P失败: {e}")
            def _update_ui_fail():
                self.get_parts_button.config(state="normal")
                self.model.part_var.set("获取失败, 请检查BV号")
                self.part_combobox['values'] = []
                self.part_combobox.config(state="disabled")

                # 失败时也要清空模型
                self.model.cid_parts_map = {}
                self.model.ordered_cids = []

            self.after(0, _update_ui_fail)
            
    def start_task(self):
        """开始发送弹幕任务的逻辑"""
        self.app.focus()  # 移除按钮焦点

        # --- 数据预处理和校验 ---
        bvid = self.model.bvid.get().strip()
        sessdata = self.model.sessdata.get().strip()
        bili_jct = self.model.bili_jct.get().strip()
        xml_path = self.model.danmaku_xml_path.get()
        
        try:
            min_delay = float(self.model.min_delay.get())
            max_delay = float(self.model.max_delay.get())
            if min_delay < 0 or max_delay < 0 or min_delay > max_delay:
                raise ValueError("延迟时间必须为正数，且最小延迟不大于最大延迟")
        except (ValueError, TypeError):
            self.logger.error("❌【输入错误】延迟时间设置不合法！")
            return
        
        if not self.model.danmaku_xml_path.get():
            self.logger.error("❌【输入错误】请先选择一个弹幕文件！")
            return
        
        if not all([bvid, xml_path, sessdata, bili_jct]):
            self.logger.error("❌【输入错误】请确保 BV号、弹幕文件、SESSDATA 和 BILI_JCT 均已填写！")
            return
        
        # 直接检查模型中是否有解析好的弹幕
        if not self.model.parsed_local_danmakus:
            self.logger.error("❌【文件错误】未加载或解析到有效弹幕，请选择一个有效的弹幕文件！")
            return
            
        # --- 使用索引安全地获取 CID ---
        selected_cid = None
        selected_index = self.part_combobox.current()
        if selected_index != -1:
            try:
                # 使用索引从 ordered_cids 列表中获取，绝对不会出错
                selected_cid = self.model.ordered_cids[selected_index]
                self.logger.info(f"已选择目标分P: {self.model.part_var.get()}, CID: {selected_cid}")
            except IndexError:
                self.logger.error("❌【程序错误】选择的索引超出了CID列表范围，请重新获取分P。")
                return
        else:
            self.logger.error("❌【操作错误】请在下拉框中选择一个分P！")
            return
            
        # --- 更新UI并启动后台任务 ---
        self._set_ui_for_task_start()
        self.stop_event.clear()

        try:
            danmakus_to_send = self.model.parsed_local_danmakus.copy()
            thread = threading.Thread(
                target=self._task_worker, 
                args=(bvid, danmakus_to_send, sessdata, bili_jct, min_delay, max_delay, selected_cid),
                daemon=True
            )
            thread.start()
        except Exception as e:
            self.logger.error(f"【程序崩溃】无法启动后台任务线程: {e}")
            self._restore_ui_after_task()

    def _task_worker(self, bvid, danmaku_list, sessdata, bili_jct, min_delay, max_delay, cid):
        """在工作线程中执行弹幕发送任务"""
        try:
            sender = BiliDanmakuSender(sessdata, bili_jct, bvid)
            sender.send_danmaku_from_list(cid, danmaku_list, min_delay, max_delay, self.stop_event)
        except Exception as e:
            self.logger.error(f"【程序崩溃】发生未捕获的严重错误: {e}")
        finally:
            self.app.after(0, self._restore_ui_after_task)
            
    def stop_task(self):
        """停止发送弹幕任务的逻辑"""
        self.logger.info("ℹ️ 用户请求停止任务，将在当前弹幕发送完毕后终止...")
        self.stop_event.set()
        self.start_button.config(state='disabled', text="正在停止")

    def _set_ui_for_task_start(self):
        """将UI设置为“任务进行中”的状态"""
        self.start_button.config(text="紧急停止", command=self.stop_task, style="danger.TButton")
        self.select_button.config(state='disabled')
        self.get_parts_button.config(state='disabled')
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.config(state='disabled')
        self.progress_bar.config(mode='indeterminate')
        self.progress_bar.start()

    def _restore_ui_after_task(self):
        """任务结束后恢复UI状态"""
        self.start_button.config(state='normal', text="开始任务", command=self.start_task, style="success.TButton")
        self.select_button.config(state='normal')
        self.get_parts_button.config(state='normal')
        self.progress_bar.stop()
        self.progress_bar.config(mode='determinate')
        self.progress_bar['value'] = 0