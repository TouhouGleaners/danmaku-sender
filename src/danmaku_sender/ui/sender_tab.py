import re
import logging
import threading
from tkinter import filedialog, scrolledtext, messagebox
from pathlib import Path
import ttkbootstrap as ttk
from ttkbootstrap.tooltip import ToolTip

from ..api.bili_api_client import BiliApiClient, BiliApiException
from ..core.bili_sender import BiliDanmakuSender
from ..core.bili_danmaku_utils import DanmakuParser, create_xml_from_danmakus
from ..config.shared_data import SenderConfig, VideoState
from ..utils.system_utils import KeepSystemAwake


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
        self.logger = logging.getLogger("SenderTab")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.stop_event = threading.Event()
        self.danmaku_parser = DanmakuParser()

        self._create_widgets()

    def _create_widgets(self):
        """创建并布局此标签页中的所有UI控件"""
        # --- 设置区 ---
        settings_frame = ttk.Labelframe(self, text="参数设置", padding=15)
        settings_frame.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        settings_frame.columnconfigure(1, weight=1)

        # BV号
        ttk.Label(settings_frame, text="BV号:").grid(row=0, column=0, sticky="w", padx=5, pady=8)
        self.bvid_entry = ttk.Entry(settings_frame, textvariable=self.model.bvid, takefocus=0)
        self.bvid_entry.grid(row=0, column=1, sticky="ew")
        self.get_parts_button = ttk.Button(settings_frame, text="获取分P", command=self.fetch_video_parts, takefocus=0)
        self.get_parts_button.grid(row=0, column=2, padx=(5, 0))

        # 分P选择
        ttk.Label(settings_frame, text="选择分P:").grid(row=1, column=0, sticky="w", padx=5, pady=8)
        self.part_combobox = ttk.Combobox(settings_frame, textvariable=self.model.part_var, state="readonly", bootstyle="secondary", takefocus=0)
        self.part_combobox.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 5))
        self.part_combobox.bind("<<ComboboxSelected>>", lambda _: (self.focus(), self.part_combobox.selection_clear(), self._on_part_selected()))
        self.part_combobox.set("请先获取分P")
        self.part_combobox.config(state="disabled")

        ttk.Label(settings_frame, text="弹幕文件:").grid(row=2, column=0, sticky="w", padx=5, pady=8)
        self.file_path_label = ttk.Label(settings_frame, text="请选择弹幕XML文件...", style="secondary.TLabel")
        self.file_path_label.grid(row=2, column=1, sticky="ew", padx=(0, 5))
        self.select_button = ttk.Button(settings_frame, text="选择文件", command=self.select_file, style="info.TButton", takefocus=0)
        self.select_button.grid(row=2, column=2, sticky="e")
        self.file_path_tooltip = ToolTip(self.file_path_label, text="") 
        
        # --- 高级设置 (延迟) ---
        advanced_frame = ttk.Labelframe(self, text="高级设置", padding=15)
        advanced_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")

        # Grid 布局：左侧区域(0)，分割线(1)，右侧区域(2)
        # 左右权重设置为1以平分空间
        advanced_frame.columnconfigure(0, weight=1)
        advanced_frame.columnconfigure(1, weight=0)
        advanced_frame.columnconfigure(2, weight=1)

        # ====== 左半区：基础间隔 ======
        left_frame = ttk.Frame(advanced_frame)
        left_frame.grid(row=0, column=0, sticky="w")
        
        ttk.Label(left_frame, text="随机间隔(秒):").pack(side="left")
        ttk.Entry(left_frame, textvariable=self.model.min_delay, width=6, takefocus=0).pack(side="left", padx=5)
        ttk.Label(left_frame, text="-").pack(side="left")
        ttk.Entry(left_frame, textvariable=self.model.max_delay, width=6, takefocus=0).pack(side="left", padx=5)

        # ====== 中间：垂直分割线 ======
        sep = ttk.Separator(advanced_frame, orient='vertical')
        sep.grid(row=0, column=1, sticky="ns", padx=20)

        # ====== 右半区：爆发模式 ======
        right_frame = ttk.Frame(advanced_frame)
        right_frame.grid(row=0, column=2, sticky="w")
        
        # 爆发阈值
        ttk.Label(right_frame, text="每(条):").pack(side="left")
        burst_entry = ttk.Entry(right_frame, textvariable=self.model.burst_size, width=5, takefocus=0)
        burst_entry.pack(side="left", padx=5)
        ToolTip(burst_entry, "爆发阈值：\n每发送多少条弹幕后，进入一次长休息。\n0 或 1 表示关闭。")
        
        # 休息时间
        ttk.Label(right_frame, text="休息(秒):").pack(side="left", padx=(10, 5))
        ttk.Entry(right_frame, textvariable=self.model.rest_min, width=5, takefocus=0).pack(side="left")
        ttk.Label(right_frame, text="-").pack(side="left", padx=2)
        ttk.Entry(right_frame, textvariable=self.model.rest_max, width=5, takefocus=0).pack(side="left")
        
        # --- 日志输出区 ---
        log_frame = ttk.Labelframe(self, text="运行日志", padding=10)
        log_frame.grid(row=2, column=0, padx=10, pady=5, sticky="nsew") 
        log_frame.columnconfigure(0, weight=1); log_frame.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=ttk.WORD, state='disabled', font=("TkDefaultFont", 9))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        
        # --- 操作区 ---
        action_frame = ttk.Frame(self, padding=(10, 10))
        action_frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew")
        action_frame.columnconfigure(0, weight=0)
        action_frame.columnconfigure(1, weight=1)
        action_frame.columnconfigure(2, weight=0)
        self.status_label = ttk.Label(action_frame, textvariable=self.model.sender_status_text, style="secondary.TLabel")
        self.status_label.grid(row=0, column=0, sticky="w")
        self.progress_bar = ttk.Progressbar(action_frame, mode='determinate', variable=self.model.sender_progress_var, style='success.Striped.TProgressbar')
        self.progress_bar.grid(row=0, column=1, sticky="ew", padx=(10, 10))
        self.start_button = ttk.Button(action_frame, text="开始任务", command=self.start_task, style="success.TButton", width=12, takefocus=0)
        self.start_button.grid(row=0, column=2, sticky="e")

    def select_file(self):
        """打开文件选择对话框，让用户选择弹幕XML文件。"""
        self.app.focus()
        file_path_str = filedialog.askopenfilename(
            title="选择弹幕XML文件", filetypes=(("XML files", "*.xml"), ("All files", "*.*"))
        )
        if not file_path_str:
            return
        file_path = Path(file_path_str)
        self.model.source_danmaku_filepath.set(str(file_path))
        self.file_path_label.config(text=file_path.name)
        self.file_path_tooltip.text = str(file_path)
        self.logger.info(f"已选择文件: {file_path}")     
        self.model.loaded_danmakus = []  # 清空旧的解析结果

        try:
            parsed_list = self.danmaku_parser.parse_xml_file(str(file_path))
            if parsed_list:
                # 将解析成功的结果存入共享模型
                self.model.loaded_danmakus = parsed_list
                self.logger.info(f"✅ 文件解析成功，共 {len(parsed_list)} 条弹幕已准备就绪。")
            else:
                self.logger.warning("⚠️ 文件解析完成，但未找到有效弹幕。请检查文件内容。")
        except Exception as e:
            self.logger.error(f"❌ 文件解析失败: {e}")
            self.model.source_danmaku_filepath.set("")  # 解析失败，清空路径，防止用户使用错误的文件
            self.file_path_label.config(text="解析失败，请重选")
    
    def _on_part_selected(self, event=None):
        """当用户从下拉框选择一个分P时，更新共享模型中的 selected_cid"""
        self.app.focus()
        selected_index = self.part_combobox.current()
        if selected_index != -1:
            try:
                # 更新分P信息
                self.model.selected_cid = self.model.ordered_cids[selected_index]
                duration_sec = self.model.ordered_durations[selected_index]
                self.model.selected_part_duration_ms = duration_sec * 1000
                self.logger.info(f"已选择目标分P: {self.model.part_var.get()}, CID: {self.model.selected_cid}, 时长: {duration_sec}秒")
            except IndexError:
                self.logger.error("程序错误：选择的索引超出了CID列表范围。")
                self.model.selected_cid = None
                self.model.selected_part_duration_ms = 0

    def fetch_video_parts(self):
        """获取视频分P列表"""
        self.app.focus()  # 移除按钮焦点

        bvid = self.model.bvid.get().strip()
        sessdata = self.model.sessdata.get().strip()
        bili_jct = self.model.bili_jct.get().strip()
        use_system_proxy = self.model.use_system_proxy.get()

        if not re.match(r'^BV[0-9A-Za-z]{10}$', bvid):
            self.logger.error("❌【输入错误】BV号格式不正确！应为BV开头的12位字符。")
            return
        
        if not all([bvid, sessdata, bili_jct]):
            self.logger.error("❌【输入错误】请确保 BV号、弹幕文件、SESSDATA 和 BILI_JCT 均已填写！")
            return
        
        self.logger.info(f"正在获取 {bvid} 的分P列表...")
        self.get_parts_button.config(state='disabled')
        self.model.part_var.set('正在获取中...')
        self.part_combobox.config(state="disabled")
        self.model.video_title.set("（正在获取视频标题...）")

        threading.Thread(
            target=self._fetch_parts_worker,
            args=(bvid, sessdata, bili_jct, use_system_proxy),
            daemon=True
        ).start()

    def _fetch_parts_worker(self, bvid, sessdata, bili_jct, use_system_proxy):
        """在工作线程中执行获取分P的API调用"""
        try:
            with BiliApiClient(sessdata, bili_jct, use_system_proxy) as api_client:
                sender = BiliDanmakuSender(api_client)
                video_info = sender.get_video_info(bvid)
            self.model.video_title.set(video_info.get('title', '未知标题'))
            pages = video_info.get('pages', [])

            # 清空旧数据
            self.model.cid_parts_map = {}
            self.model.ordered_cids = []
            self.model.ordered_durations = []
            display_parts = []

            # 遍历API返回结果，填充模型数据
            for p in pages:
                cid = p['cid']
                part_name = f"P{p['page']} - {p['part']}"
                duration_sec = p.get('duration', 0)
                self.model.cid_parts_map[cid] = part_name
                self.model.ordered_cids.append(cid)
                self.model.ordered_durations.append(duration_sec)
                display_parts.append(part_name)

            def _update_ui_success():
                """在主线程中更新UI的回调函数"""
                if display_parts:
                    self.part_combobox['values'] = display_parts
                    self.part_combobox.config(state="readonly")

                    if len(display_parts) == 1:
                        self.logger.info(f"✅ 成功获取到 1 个分P，已为您自动选中。")
                        self.model.part_var.set(display_parts[0])
                    else:
                        self.logger.info(f"✅ 成功获取到 {len(display_parts)} 个分P，请手动选择。")
                        self.model.part_var.set("请在下拉框中选择一个分P")

                    self._on_part_selected()  # 自动选择或提示后，都触发一次更新逻辑
                else:
                    self.part_combobox['values'] = []
                    self.model.part_var.set("未找到任何分P")
                
                self.get_parts_button.config(state='normal')
            
            self.app.after(0, _update_ui_success)
        except (BiliApiException, ValueError, RuntimeError) as e:
            self.logger.error(f"❌ 获取分P失败: {e}")
            def _update_ui_fail():
                self.get_parts_button.config(state="normal")
                self.model.part_var.set("获取失败, 请检查BV号")
                self.part_combobox['values'] = []
                self.part_combobox.config(state="disabled")

                # 失败时清空模型
                self.model.cid_parts_map = {}
                self.model.ordered_cids = []
                self.model.ordered_durations = []
                self.model.video_title.set("（未获取到视频标题）")

            self.after(0, _update_ui_fail)
            
    def start_task(self):
        """开始发送弹幕任务的逻辑"""
        self.app.focus()  # 移除按钮焦点

        # 获取并校验配置
        config = self.model.get_sender_config()
        if config is None:
            self.logger.error("❌【输入错误】延迟时间设置不合法！请输入有效的数字。")
            return

        if not config.is_valid():
            self.logger.error("❌【配置错误】请确保 SESSDATA/BILI_JCT 已填写，且延迟时间为正数！")
            return
        
        # 获取视频状态
        video_state = self.model.get_video_state()

        # 校验业务逻辑
        if not video_state.bvid:
            self.logger.error("❌【输入错误】BV号不能为空！")
            return
            
        if not video_state.loaded_danmakus:
            self.logger.error("❌【文件错误】未加载或解析到有效弹幕，请选择一个有效的弹幕文件！")
            return

        if not video_state.selected_cid:
            self.logger.error("❌【操作错误】请先获取并选择一个分P！")
            return
        
        # --- 弹窗确认信息 ---
        burst_info = ""
        if config.burst_size > 1:
            burst_info = f"\n(已开启爆发模式: 每 {config.burst_size} 条休息 {config.rest_min}-{config.rest_max} 秒)"

        confirmation_message = (
            f"即将为视频：\n"
            f"《{video_state.video_title}》| {video_state.selected_part_name}\n"
            f"发送 {video_state.danmaku_count} 条弹幕{burst_info}，是否继续？"
        )
        
        if not messagebox.askyesno("确认发送", confirmation_message, parent=self.app):
            self.logger.info("用户取消了弹幕发送任务。")
            return
            
        # --- 更新UI并启动后台任务 ---
        self._set_ui_for_task_start()
        self.stop_event.clear()

        try:
            thread = threading.Thread(
                target=self._task_worker, 
                args=(config, video_state), 
                daemon=True
            )
            thread.start()
        except Exception as e:
            self.logger.error(f"【程序崩溃】无法启动后台任务线程: {e}")
            self._restore_ui_after_task()

    def _task_worker(self, config: SenderConfig, video_state: VideoState):
        """在工作线程中执行弹幕发送任务"""
        danmakus_to_send = video_state.loaded_danmakus.copy()
        sender = None

        try:
            with KeepSystemAwake(config.prevent_sleep):
                with BiliApiClient.from_config(config) as api_client:
                    sender = BiliDanmakuSender(api_client)

                    def _progress_updater(attempted, total):
                        """一个在后台线程被调用的函数，用于向主线程发送UI更新请求"""
                        if total > 0:
                            progress_percent = (attempted / total) * 100
                            self.app.after(0, lambda: self.model.sender_progress_var.set(progress_percent))

                    sender.send_danmaku_from_list(
                        bvid=video_state.bvid, 
                        cid=video_state.selected_cid, 
                        danmakus=danmakus_to_send, 
                        config=config, 
                        stop_event=self.stop_event, 
                        progress_callback=_progress_updater
                    )
        except (BiliApiException, ValueError) as e:
            self.logger.error(f"【任务启动失败】无法初始化API客户端: {e}")
        except Exception as e:
            self.logger.error(f"【程序崩溃】发生未捕获的严重错误: {e}")
        finally:
            if sender:
                self.app.after(0, lambda: self._finalize_sending_task(sender))
            else:
                self.app.after(0, self._restore_ui_after_task)

    def _finalize_sending_task(self, sender: BiliDanmakuSender):
        """
        在弹幕发送任务完成后，于主线程中执行最终处理。
        此方法负责：
        1. 恢复用户界面到初始状态。
        2. 检查 `sender` 实例中是否有未成功发送的弹幕。
        3. 如果存在未发送弹幕，弹窗询问用户是否将其保存为新的XML文件。
        Args:
            sender (BiliDanmakuSender): 执行发送任务的 BiliDanmakuSender 实例。
        """
        self._restore_ui_after_task()

        if sender.unsent_danmakus:
            self.after(100, lambda: self._ask_save_unsent_danmakus(sender))
        else:
            self.logger.info("所有弹幕均已成功发送，或无未发送弹幕。")

    def _ask_save_unsent_danmakus(self, sender: BiliDanmakuSender):
        """独立的逻辑处理函数，仅负责弹窗和保存"""
        if not self.winfo_exists():
            return

        if not sender.unsent_danmakus:
            self.logger.info("所有弹幕均已成功发送，或无未发送弹幕。")
            return
        
        self.logger.info(f"检测到 {len(sender.unsent_danmakus)} 条弹幕未发送成功。")

        should_save = messagebox.askyesno(
            title="保存未发送弹幕",
            message=f"有 {len(sender.unsent_danmakus)} 条弹幕未能发送成功。\n"
                    "是否将它们保存为新的XML文件，以便后续重新发送？",
            parent=self.app
        )

        if should_save:
            file_path_str = filedialog.asksaveasfilename(
                title="保存未发送弹幕为XML文件",
                defaultextension=".xml",
                filetypes=(("XML files", "*.xml"), ("All files", "*.*")),
                initialfile="unsent_danmakus.xml"
            )
            if file_path_str:
                create_xml_from_danmakus(sender.unsent_danmakus, file_path_str)
                self.logger.info(f"已将未发送弹幕保存到 '{file_path_str}'。")
            else:
                self.logger.info("用户取消了文件路径选择。")
        else:
            self.logger.info("用户选择不保存未发送弹幕。")

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
        self.model.sender_progress_var.set(0)
        self.model.sender_status_text.set("发送器：运行中...")

    def _restore_ui_after_task(self):
        """任务结束后恢复UI状态"""
        self.start_button.config(state='normal', text="开始任务", command=self.start_task, style="success.TButton")
        self.select_button.config(state='normal')
        self.get_parts_button.config(state='normal')
        self.progress_bar.stop()
        self.progress_bar.config(mode='determinate')
        self.progress_bar['value'] = 0

        final_progress = self.model.sender_progress_var.get()
        if final_progress < 100:
             self.app.after(1000, lambda: self.model.sender_progress_var.set(0))
        self.model.sender_status_text.set("发送器：待命")