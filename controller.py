import logging
import threading
from main import BiliDanmakuSender


class AppController:
    def __init__(self, model, app):
        """控制器初始化

        Args:
            model: 数据模型 (ShareDataModel的实例)
            app: 主GUI应用 (Application的实例)，用于调用after方法实现线程安全UI更新
        """
        self.model = model
        self.app = app

        self.stop_event = threading.Event()
        self.video_pages = []
        self.display_parts = []
        self.parts_loaded = False

    def fetch_video_parts(self):
        """获取视频分P列表"""
        self.app.focus()  # 移除按钮焦点

        bvid = self.model.bvid.get().strip()
        sessdata = self.model.sessdata.get().strip()
        bili_jct = self.model.bili_jct.get().strip()

        if not all([bvid, sessdata, bili_jct]):
            logging.error("❌【输入错误】请确保 BV号、弹幕文件、SESSDATA 和 BILI_JCT 均已填写！")
            return
        
        logging.info(f"正在获取 {bvid} 的分P列表...")
        self.app.get_parts_button.config(state='disabled')
        self.model.part_var.set('正在获取中...')
        self.app.part_combobox.config(state="disabled")

        threading.Thread(target=self._fetch_parts_worker, args=(bvid, sessdata, bili_jct), daemon=True).start()

    def _fetch_parts_worker(self, bvid, sessdata, bili_jct):
        """在工作线程中执行获取分P的API调用"""
        try:
            sender = BiliDanmakuSender(sessdata, bili_jct, bvid)
            video_info = sender.get_video_info()
            self.video_pages = video_info.get('pages', [])
            
            self.display_parts = [f"P{p['page']} - {p['part']}" for p in self.video_pages]
            def _update_ui_success():
                # 这是一个在主线程中更新UI的回调函数
                if self.display_parts:
                    logging.info(f"✅ 成功获取到 {len(self.display_parts)} 个分P，已为您选中第一个")
                    self.app.part_combobox['values'] = self.display_parts
                    self.model.part_var.set(self.display_parts[0])
                    self.app.part_combobox.config(state="readonly")
                    self.parts_loaded = True
                else:
                    self.app.part_combobox['values'] = []
                    self.model.part_var.set("未找到任何分P" if self.video_pages is not None else "获取失败")
                    self.parts_loaded = False
                
                self.app.get_parts_button.config(state='normal')
            
            # 使用 self.app.after() 来确保UI更新在主线程中安全地执行
            self.app.after(0, _update_ui_success)
        except Exception as e:
            logging.error(f"❌ 获取分P失败: {e}")
            def _update_ui_fail():
                self.app.get_parts_button.config(state="normal")
                self.model.part_var.set("获取失败, 请检查BV号")
                self.app.part_combobox['values'] = []
                self.app.part_combobox.config(state="disabled")
                self.parts_loaded = False
            
            self.app.after(0, _update_ui_fail)
            
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
            logging.error("❌【输入错误】延迟时间设置不合法！")
            return
        if not all([bvid, xml_path, sessdata, bili_jct]):
            logging.error("❌【输入错误】请确保 BV号、弹幕文件、SESSDATA 和 BILI_JCT 均已填写！")
            return
        
        if not self.parts_loaded:
            logging.error("❌【操作错误】请先成功获取并选择一个分P！")
            return
            
        # --- 获取 CID ---
        selected_part_str = self.model.part_var.get()
        try:
            selected_index = self.display_parts.index(selected_part_str)
            selected_cid = self.video_pages[selected_index]['cid']
            logging.info(f"已选择目标分P: {selected_part_str}, CID: {selected_cid}")
        except (ValueError, IndexError):
            logging.error("❌【程序错误】选择的分P与列表不匹配，请重新获取分P")
            return
            
        # --- 更新UI进入任务状态 ---
        self._set_ui_for_task_start()
        # --- 启动后台任务 ---
        self.stop_event.clear()
        try:
            thread = threading.Thread(
                target=self._task_worker, 
                args=(bvid, xml_path, sessdata, bili_jct, min_delay, max_delay, selected_cid),
                daemon=True
            )
            thread.start()
        except Exception as e:
            logging.error(f"【程序崩溃】无法启动后台任务线程: {e}")
            self._restore_ui_after_task()

    def _task_worker(self, bvid, xml_path, sessdata, bili_jct, min_delay, max_delay, cid):
        """在工作线程中执行弹幕发送任务"""
        try:
            sender = BiliDanmakuSender(sessdata, bili_jct, bvid)
            sender.send_danmaku_from_xml(cid, xml_path, min_delay, max_delay, self.stop_event)
        except Exception as e:
            logging.error(f"【程序崩溃】发生未捕获的严重错误: {e}")
        finally:
            self.app.after(0, self._restore_ui_after_task)
            
    def stop_task(self):
        """停止发送弹幕任务的逻辑"""
        logging.info("ℹ️ 用户请求停止任务，将在当前弹幕发送完毕后终止...")
        self.stop_event.set()
        self.app.start_button.config(state='disabled', text="正在停止")

    def _set_ui_for_task_start(self):
        """将UI设置为“任务进行中”的状态"""
        self.app.start_button.config(text="紧急停止", command=self.stop_task, style="danger.TButton")
        self.app.select_button.config(state='disabled')
        self.app.get_parts_button.config(state='disabled')
        self.app.log_text.config(state='normal')
        self.app.log_text.delete('1.0', 'end')
        self.app.log_text.config(state='disabled')
        self.app.progress_bar.config(mode='indeterminate')
        self.app.progress_bar.start()
    def _restore_ui_after_task(self):
        """任务结束后恢复UI状态"""
        self.app.start_button.config(state='normal', text="开始任务", command=self.start_task, style="success.TButton")
        self.app.select_button.config(state='normal')
        self.app.get_parts_button.config(state='normal')
        self.app.progress_bar.stop()
        self.app.progress_bar.config(mode='determinate')
        self.app.progress_bar['value'] = 0