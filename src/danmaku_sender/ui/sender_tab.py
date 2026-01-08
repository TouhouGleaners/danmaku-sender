import logging
import threading
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QComboBox, QLabel, QGroupBox, QTextEdit,
    QProgressBar, QTabWidget, QSpinBox, QDoubleSpinBox, QFrame,
    QFileDialog, QMessageBox
)
from PySide6.QtGui import QTextCursor

from ..core.bili_danmaku_utils import DanmakuParser, create_xml_from_danmakus
from ..core.workers import FetchInfoWorker, SendTaskWorker


class SenderTab(QWidget):
    def __init__(self):
        super().__init__()
        self._state = None
        self.logger = logging.getLogger("SenderTab")
        self.stop_event = threading.Event()
        self.danmaku_parser = DanmakuParser()

        self._is_task_running = False

        self._fetch_worker = None
        self._send_worker = None

        self._create_ui()
        self._connect_ui_logic()

    def _create_ui(self):
        # 主布局 - 垂直布局
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- 基础参数区 ---
        basic_group = QGroupBox("基础参数")
        basic_layout = QFormLayout()

        # BV + 获取按钮
        bv_layout = QHBoxLayout()
        self.bv_input = QLineEdit()
        self.bv_input.setPlaceholderText("请输入视频BV号")
        self.fetch_btn = QPushButton("获取分P")
        bv_layout.addWidget(self.bv_input)
        bv_layout.addWidget(self.fetch_btn)

        # 分P选择
        self.part_combo = QComboBox()
        self.part_combo.setPlaceholderText("请选择分P")
        self.part_combo.setEnabled(False)

        # 弹幕文件选择
        file_layout = QHBoxLayout()
        self.file_input = QLineEdit()
        self.file_input.setReadOnly(True)
        self.file_input.setPlaceholderText("请选择弹幕 XML 文件")
        self.file_btn = QPushButton("选择文件")
        file_layout.addWidget(self.file_input)
        file_layout.addWidget(self.file_btn)

        basic_layout.addRow(QLabel("视频BV号:"), bv_layout)
        basic_layout.addRow(QLabel("分P选择:"), self.part_combo)
        basic_layout.addRow(QLabel("弹幕文件:"), file_layout)

        basic_group.setLayout(basic_layout)
        main_layout.addWidget(basic_group)

        # --- 策略设置区 ---
        strategy_tabs = QTabWidget()

        # Tab 1: 发送设置
        delay_tab = QWidget()
        delay_layout = QHBoxLayout()
        delay_layout.setContentsMargins(10, 20, 10, 20)
        
        delay_layout.addWidget(QLabel("随机间隔(秒):"))
        self.min_delay = QDoubleSpinBox()
        self.min_delay.setRange(0.1, 60.0)
        self.min_delay.setValue(8.0)
        self.min_delay.setSingleStep(0.5)
        delay_layout.addWidget(self.min_delay)

        delay_layout.addWidget(QLabel("-"))

        self.max_delay = QDoubleSpinBox()
        self.max_delay.setRange(0.1, 60.0)
        self.max_delay.setValue(8.5)
        self.max_delay.setSingleStep(0.5)
        delay_layout.addWidget(self.max_delay)

        # 分隔线
        delay_layout.addSpacing(15)
        v_line = QFrame()
        v_line.setFrameShape(QFrame.VLine)
        v_line.setFrameShadow(QFrame.Sunken)
        delay_layout.addWidget(v_line)
        delay_layout.addSpacing(15)

        # 爆发模式
        delay_layout.addWidget(QLabel("爆发模式: 每"))

        self.burst_size = QSpinBox()
        self.burst_size.setRange(0, 100)
        self.burst_size.setToolTip("0 或 1 表示关闭爆发模式")
        delay_layout.addWidget(self.burst_size)

        delay_layout.addWidget(QLabel("条，休息"))

        self.burst_rest_min = QDoubleSpinBox()
        self.burst_rest_min.setRange(0.0, 300.0)
        self.burst_rest_min.setValue(10.0)
        self.burst_rest_min.setFixedWidth(60)
        delay_layout.addWidget(self.burst_rest_min)

        delay_layout.addWidget(QLabel("-"))

        self.burst_rest_max = QDoubleSpinBox()
        self.burst_rest_max.setRange(0.0, 300.0)
        self.burst_rest_max.setValue(20.0)
        self.burst_rest_max.setFixedWidth(60)
        delay_layout.addWidget(self.burst_rest_max)

        delay_layout.addWidget(QLabel("秒"))

        delay_layout.addStretch()
        
        delay_tab.setLayout(delay_layout)
        strategy_tabs.addTab(delay_tab, "发送延迟")

        # Tab 2: 自动终止
        stop_tab = QWidget()
        stop_layout = QHBoxLayout()
        stop_layout.setContentsMargins(10, 20, 10, 20)

        # 数量限制
        stop_layout.addWidget(QLabel("已发送 >="))
        self.stop_count = QSpinBox()
        self.stop_count.setRange(0, 99999)
        stop_layout.addWidget(self.stop_count)
        stop_layout.addWidget(QLabel("条"))

        stop_layout.addSpacing(20)
        v_line2 = QFrame()
        v_line2.setFrameShape(QFrame.VLine)
        v_line2.setFrameShadow(QFrame.Sunken)
        stop_layout.addWidget(v_line2)
        stop_layout.addSpacing(20)

        # 时间限制
        stop_layout.addWidget(QLabel("已用时 >="))
        self.stop_time = QSpinBox()
        self.stop_time.setRange(0, 99999)
        stop_layout.addWidget(self.stop_time)
        stop_layout.addWidget(QLabel("分钟"))

        stop_layout.addStretch()
        stop_layout.addWidget(QLabel("(0为不限制)"))

        stop_tab.setLayout(stop_layout)
        strategy_tabs.addTab(stop_tab, "自动终止")

        main_layout.addWidget(strategy_tabs)

        # --- 日志区 ---
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout()
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)
        log_group.setLayout(log_layout)

        main_layout.addWidget(log_group, stretch=1)

        # --- 操作区 ---
        action_layout = QHBoxLayout()

        self.status_label = QLabel("发送器：待命")
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.start_btn = QPushButton("开始发送")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #2ecc71; 
                color: white; 
                font-weight: bold; 
                padding: 6px 20px;
                border-radius: 4px;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)

        action_layout.addWidget(self.status_label)
        action_layout.addWidget(self.progress_bar, stretch=1)
        action_layout.addWidget(self.start_btn)

        main_layout.addLayout(action_layout)

        self.setLayout(main_layout)

    def _connect_ui_logic(self):
        self.file_btn.clicked.connect(self.select_file)
        self.fetch_btn.clicked.connect(self.fetch_video_info)
        self.part_combo.currentIndexChanged.connect(self.on_part_selected)
        self.start_btn.clicked.connect(self.toggle_task)

    def bind_state(self, state):
        """将 UI 控件绑定到 AppState"""
        if self._state is state:
            return
            
        if self._state is not None:
            self._disconnect_signals()
        
        self._state = state
        config = state.sender_config
        video_state = state.video_state

        # --- 初始化 UI 内容 ---
        self.min_delay.setValue(config.min_delay)
        self.max_delay.setValue(config.max_delay)
        self.burst_size.setValue(config.burst_size)
        self.burst_rest_min.setValue(config.rest_min)
        self.burst_rest_max.setValue(config.rest_max)
        self.stop_count.setValue(config.stop_after_count)
        self.stop_time.setValue(config.stop_after_time)

        # 视频状态初始化
        self.bv_input.setText(video_state.bvid)
        if video_state.selected_part_name:
            self.part_combo.setPlaceholderText(video_state.selected_part_name)

        # --- 绑定信号槽 (UI -> State) ---
        # 延迟设置
        self.min_delay.valueChanged.connect(lambda v: setattr(config, "min_delay", v))
        self.max_delay.valueChanged.connect(lambda v: setattr(config, 'max_delay', v))

        # 爆发模式
        self.burst_size.valueChanged.connect(lambda v: setattr(config, 'burst_size', v))
        self.burst_rest_min.valueChanged.connect(lambda v: setattr(config, 'rest_min', v))
        self.burst_rest_max.valueChanged.connect(lambda v: setattr(config, 'rest_max', v))
        
        # 自动停止
        self.stop_count.valueChanged.connect(lambda v: setattr(config, 'stop_after_count', v))
        self.stop_time.valueChanged.connect(lambda v: setattr(config, 'stop_after_time', v))

        # BV号同步
        self.bv_input.textChanged.connect(lambda t: setattr(video_state, 'bvid', t.strip()))

    def _disconnect_signals(self):
        """安全断开所有信号连接"""
        signals = [
            self.min_delay.valueChanged,
            self.max_delay.valueChanged,
            self.burst_size.valueChanged,
            self.burst_rest_min.valueChanged,
            self.burst_rest_max.valueChanged,
            self.stop_count.valueChanged,
            self.stop_time.valueChanged,
            self.bv_input.textChanged
        ]
        for sig in signals:
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass

    def append_log(self, message: str):
        """外部调用的日志接口"""
        self.log_output.append(message) 
        self.log_output.moveCursor(QTextCursor.End)

    def select_file(self):
        """文件选择逻辑"""
        if not self._state:
            return

        file_path, _ = QFileDialog.getOpenFileName(self, "选择弹幕XML文件", "", "XML Files (*.xml);;All Files (*.*)")
        if file_path:
            self._state.video_state.loaded_danmakus = []

            try:
                parsed = self.danmaku_parser.parse_xml_file(file_path)
                if parsed:
                    self.file_input.setText(Path(file_path).name)
                    self._state.video_state.loaded_danmakus = parsed
                    self.logger.info(f"✅ 文件解析成功，共 {len(parsed)} 条弹幕。")
                else:
                    self.file_input.clear()
                    self.logger.warning("⚠️ 文件解析完成但无有效弹幕。")
            except Exception as e:
                self.file_input.clear()
                self.logger.error(f"❌ 解析失败: {e}")
                QMessageBox.critical(self, "解析失败", str(e))

    def fetch_video_info(self):
        """获取视频信息"""
        if not self._state:
            return
        
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            self.logger.warning("正在获取视频信息，请稍候...")
            return

        bvid = self.bv_input.text().strip()
        if not bvid:
            QMessageBox.warning(self, "输入错误", "请输入BV号")
            return
        
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("获取中")
        self.part_combo.clear()
        self.part_combo.setEnabled(False)

        auth_config = self._state.get_api_auth()

        self._fetch_worker = FetchInfoWorker(bvid, auth_config, parent=self)
        self._fetch_worker.finished_success.connect(self._on_fetch_success)
        self._fetch_worker.finished_error.connect(self._on_fetch_error)
        self._fetch_worker.finished.connect(self._fetch_worker.deleteLater)
        self._fetch_worker.start()

    def _on_fetch_success(self, info: dict):
        """视频信息获取成功"""
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("获取分P")
        self.part_combo.setEnabled(True)
        self._fetch_worker = None
        
        self._state.video_state.video_title = info.get('title', '未知标题')
        self._state.video_state.cid_parts_map = {}

        pages = info.get('pages', [])
        self.logger.info(f"获取成功: {info.get('title')}, 共 {len(pages)} 个分P")

        for p in pages:
            cid = p.get('cid')
            page_num = p.get('page', '?')
            part_title = p.get('part', '未知分P标题')
            duration = p.get('duration', 0)

            if not cid:
                continue

            part_name = f"P{page_num} - {part_title}"

            self.part_combo.addItem(part_name, userData={'cid': cid, 'duration': duration})
            self._state.video_state.cid_parts_map[cid] = part_name

        if pages:
            self.part_combo.setCurrentIndex(0)

    def _on_fetch_error(self, err_msg: str):
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("获取分P")
        self._fetch_worker = None

        self.part_combo.clear()
        self.part_combo.addItem(f"获取失败，请重试")
        self.part_combo.setEnabled(False) 

        self.logger.error(f"获取视频信息失败: {err_msg}")
        QMessageBox.warning(self, "获取失败", f"无法获取视频信息:\n{err_msg}")

    def on_part_selected(self, index):
        """处理分P选择变化"""
        if index < 0:
            return

        data = self.part_combo.itemData(index)
        if not data or not isinstance(data, dict):
            return
        
        cid = self.part_combo.itemData(index)['cid']
        duration = self.part_combo.itemData(index)['duration']
        part_name = self.part_combo.currentText()
        
        self._state.video_state.selected_cid = cid
        self._state.video_state.selected_part_duration_ms = duration * 1000
        self._state.video_state.selected_part_name = part_name
        self.logger.info(f"已选择分P: {part_name} (CID: {cid})")

    def toggle_task(self):
        """开始/停止 任务"""
        if not self._state:
            return
        
        # 如果正在运行 -> 停止
        if self._is_task_running:
            self.stop_event.set()
            self.start_btn.setEnabled(False)
            self.start_btn.setText("正在停止...")
            self.logger.info("正在请求停止任务...")
            return

        # 防并发
        if self._send_worker is not None and self._send_worker.isRunning():
            self.logger.warning("上一轮任务尚未彻底结束，请稍候...")
            return
        


        # 如果未运行 -> 开始
        # 校验
        state = self._state

        if self._state.validator_is_dirty:
            QMessageBox.warning(
                self, 
                "存在未保存的修改", 
                "检测到【弹幕校验器】中有未应用的修改！\n\n请先返回校验器点击“应用所有修改”，\n否则发送的将是旧的、未修复的弹幕。"
            )
            return

        if not state.video_state.is_ready_to_send:
            QMessageBox.warning(self, "条件不足", "请确保 BV号、分P、弹幕文件 均已就绪。")
            return

        if not state.sessdata or not state.bili_jct:
            QMessageBox.warning(self, "凭证缺失", "请先在【全局设置】页填入 SESSDATA 和 BILI_JCT。")
            return

        # UI 锁定
        self._set_ui_for_task_start()

        # 构造配置
        auth_config = state.get_api_auth()
        strategy_config = state.sender_config
        
        # 启动线程
        self._send_worker = SendTaskWorker(
            bvid=state.video_state.bvid,
            cid=state.video_state.selected_cid,
            danmakus=state.video_state.loaded_danmakus,
            auth_config=auth_config,
            strategy_config=strategy_config,
            stop_event=self.stop_event,
            parent=self
        )
        self._send_worker.progress_updated.connect(self._on_send_progress)
        self._send_worker.task_finished.connect(self._on_send_finished)
        self._send_worker.log_message.connect(self.append_log)
        self._send_worker.finished.connect(self._send_worker.deleteLater)
        self._send_worker.start()

    def _on_send_progress(self, attempted, total):
        if total > 0:
            val = int((attempted / total) * 100)
            self.progress_bar.setValue(val)
        self.status_label.setText(f"发送中: {attempted}/{total}")

    def _on_send_finished(self, sender_instance):
        """任务结束后的清理与保存逻辑"""
        # 恢复 UI
        self._reset_ui_after_task()
        self.status_label.setText("发送器：任务结束")
        
        # 检查是否有失败弹幕
        if sender_instance and sender_instance.unsent_danmakus:
            count = len(sender_instance.unsent_danmakus)
            reply = QMessageBox.question(
                self, "保存失败弹幕", 
                f"有 {count} 条弹幕发送失败。\n是否保存为新的 XML 文件以便重新发送？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                file_path, _ = QFileDialog.getSaveFileName(self, "保存XML", "unsent.xml", "XML Files (*.xml)")
                if file_path:
                    try:
                        create_xml_from_danmakus(sender_instance.unsent_danmakus, file_path)
                        self.logger.info(f"未发送弹幕已保存至: {file_path}")
                        QMessageBox.information(self, "保存成功", f"文件已保存至：\n{file_path}")
                    except Exception as e:
                        self.logger.error(f"保存XML文件失败: {e}")
                        QMessageBox.critical(self, "保存失败", f"无法写入文件，请检查权限或路径。\n错误信息: {e}")

        self._send_worker = None

    def _set_ui_for_task_start(self):
        """任务开始时的 UI 状态设置"""
        self._is_task_running = True
        self.stop_event.clear()
        
        # 按钮变红
        self.start_btn.setText("紧急停止")
        self.start_btn.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 6px 20px; border-radius: 4px;")
        
        # 锁定输入
        self.fetch_btn.setEnabled(False)
        self.file_btn.setEnabled(False)
        self.part_combo.setEnabled(False)
        self.bv_input.setReadOnly(True)
        
        # 重置进度
        self.log_output.clear()
        self.progress_bar.setValue(0)

    def _reset_ui_after_task(self):
        """任务结束后的 UI 状态复位"""
        self._is_task_running = False

        # 按钮变绿
        self.start_btn.setText("开始发送")
        self.start_btn.setEnabled(True)
        self.start_btn.setStyleSheet("QPushButton { background-color: #2ecc71; color: white; font-weight: bold; padding: 6px 20px; border-radius: 4px; }")
        
        # 解锁输入
        self.fetch_btn.setEnabled(True)
        self.file_btn.setEnabled(True)
        self.part_combo.setEnabled(True)
        self.bv_input.setReadOnly(False)