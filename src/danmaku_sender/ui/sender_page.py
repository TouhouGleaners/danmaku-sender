import logging
import threading
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QComboBox, QLabel, QGroupBox, QTextEdit, QCheckBox,
    QProgressBar, QTabWidget, QSpinBox, QDoubleSpinBox, QFrame,
    QFileDialog, QMessageBox
)
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import Qt, QDateTime

from .framework.binder import UIBinder

from ..core.models.video import VideoInfo
from ..core.services.danmaku_exporter import create_xml_from_danmakus
from ..core.services.danmaku_parser import DanmakuParser
from ..core.state import AppState
from .workers import FetchInfoWorker, SendTaskWorker
from ..utils.string_utils import parse_bilibili_link
from ..utils.time_utils import format_seconds_to_duration


class SenderPage(QWidget):
    def __init__(self):
        super().__init__()
        self._state: AppState | None = None
        self.logger = logging.getLogger("SenderPage")
        self.stop_event = threading.Event()
        self.danmaku_parser = DanmakuParser()

        self._is_task_running = False
        self._fetch_worker = None
        self._send_worker = None
        self._pending_part_index: int | None = None 

        self._create_ui()
        self._connect_ui_logic()

    def _create_ui(self):
        # 主布局 - 垂直布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- 基础参数策略区 ---
        self.basic_group = BasicParamsGroup()
        self.strategy_tabs = StrategySettingsTabs()

        main_layout.addWidget(self.basic_group)
        main_layout.addWidget(self.strategy_tabs)

        # --- 日志区 ---
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout(log_group)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)

        main_layout.addWidget(log_group, stretch=1)

        # --- 操作区 ---
        action_layout = QHBoxLayout()

        # 状态
        self.status_label = QLabel("发送器：待命")

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        # 按钮
        self.start_btn = QPushButton("开始发送")
        self.start_btn.setFixedWidth(100)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setProperty("action", "true")
        self.start_btn.setProperty("state", "ready")

        action_layout.addWidget(self.status_label)
        action_layout.addWidget(self.progress_bar, stretch=1)
        action_layout.addWidget(self.start_btn)

        main_layout.addLayout(action_layout)

    def _connect_ui_logic(self):
        # 子组件信号
        self.basic_group.file_btn.clicked.connect(self.select_file)
        self.basic_group.fetch_btn.clicked.connect(self.fetch_video_info)
        self.basic_group.part_combo.currentIndexChanged.connect(self.on_part_selected)

        # 本地信号
        self.start_btn.clicked.connect(self.toggle_task)

    def bind_state(self, state: AppState):
        """将 UI 控件与 AppState 进行双向绑定"""
        if self._state is state:
            return

        self._state = state

        self.basic_group.bind_state(state)
        self.strategy_tabs.bind_state(state)

    def append_log(self, message: str):
        """外部调用的日志接口"""
        self.log_output.append(message)
        self.log_output.moveCursor(QTextCursor.MoveOperation.End)

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
                    self.basic_group.file_input.setText(Path(file_path).name)
                    self._state.video_state.loaded_danmakus = parsed
                    self.logger.info(f"✅ 文件解析成功，共 {len(parsed)} 条弹幕。")
                else:
                    self.basic_group.file_input.clear()
                    self.logger.warning("⚠️ 文件解析完成但无有效弹幕。")
            except Exception as e:
                self.basic_group.file_input.clear()
                self.logger.error(f"❌ 解析失败: {e}")
                QMessageBox.critical(self, "解析失败", str(e))

    def fetch_video_info(self):
        """获取视频信息"""
        if not self._state:
            return

        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            self.logger.warning("正在获取视频信息，请稍候...")
            return

        raw_input = self.basic_group.bv_input.text().strip()
        if not raw_input:
            QMessageBox.warning(self, "输入错误", "请输入BV号或视频链接")
            return

        bvid, p_index = parse_bilibili_link(raw_input)

        if not bvid:
            QMessageBox.warning(self, "格式错误", "未能识别有效的 BV 号。\n请检查输入内容是否正确。")
            self._pending_part_index = None
            return

        self.basic_group.bv_input.setText(bvid)
        self._pending_part_index = p_index

        self.basic_group.fetch_btn.setEnabled(False)
        self.basic_group.fetch_btn.setText("获取中")
        self.basic_group.part_combo.clear()
        self.basic_group.part_combo.setEnabled(False)

        auth_config = self._state.get_api_auth()

        self._fetch_worker = FetchInfoWorker(bvid, auth_config, parent=self)
        self._fetch_worker.finished_success.connect(self._on_fetch_success)
        self._fetch_worker.finished_error.connect(self._on_fetch_error)
        self._fetch_worker.finished.connect(self._fetch_worker.deleteLater)
        self._fetch_worker.start()

    def _on_fetch_success(self, info: VideoInfo):
        """视频信息获取成功"""
        if not self._state:
            return

        self.basic_group.fetch_btn.setEnabled(True)
        self.basic_group.fetch_btn.setText("获取分P")
        self.basic_group.part_combo.setEnabled(True)
        self._fetch_worker = None
        
        self._state.video_state.video_title = info.title
        self._state.video_state.cid_parts_map = {}

        parts = info.parts
        self.logger.info(f"获取成功: {info.title}, 共 {len(parts)} 个分P")

        for p in parts:
            cid = p.cid
            page_num = p.page
            part_title = p.title
            duration = p.duration

            if not cid:
                continue

            part_name = f"P{page_num} - {part_title}"

            self.basic_group.part_combo.addItem(part_name, userData={'cid': cid, 'duration': duration})
            self._state.video_state.cid_parts_map[cid] = part_name

        if parts:
            if (self._pending_part_index is not None and 
                0 <= self._pending_part_index < self.basic_group.part_combo.count()):

                self.basic_group.part_combo.setCurrentIndex(self._pending_part_index)
                self.logger.info(f"🔗 智能链接解析: 自动定位到第 {self._pending_part_index + 1} P")
            else:
                self.basic_group.part_combo.setCurrentIndex(0)

            self._pending_part_index = None

    def _on_fetch_error(self, err_msg: str):
        self.basic_group.fetch_btn.setEnabled(True)
        self.basic_group.fetch_btn.setText("获取分P")
        self._fetch_worker = None

        self._pending_part_index = None

        self.basic_group.part_combo.clear()
        self.basic_group.part_combo.addItem(f"获取失败，请重试")
        self.basic_group.part_combo.setEnabled(False) 

        self.logger.error(f"获取视频信息失败: {err_msg}")
        QMessageBox.warning(self, "获取失败", f"无法获取视频信息:\n{err_msg}")

    def on_part_selected(self, index):
        """处理分P选择变化"""
        if not self._state:
            return

        if index < 0:
            return

        data = self.basic_group.part_combo.itemData(index)
        if not data or not isinstance(data, dict):
            return

        cid = data['cid']
        duration = data['duration']
        part_name = self.basic_group.part_combo.currentText()

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
            self.start_btn.setText("停止中...")
            self.logger.info("发送器：正在请求中止...")
            self.progress_bar.setFormat("%p% (正在停止...)")
            return

        # 防并发
        if self._send_worker is not None and self._send_worker.isRunning():
            self.logger.warning("上一轮任务尚未彻底结束，请稍候...")
            return

        # 如果未运行 -> 开始
        # 校验
        state = self._state

        if state.editor_is_dirty:
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
            video_title=state.video_state.video_title,
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

            # ETA 计算逻辑
            remaining = total - attempted
            if remaining > 0:
                eta_sec = self._calculate_eta_seconds(attempted, total)
                duration = format_seconds_to_duration(eta_sec)
                finish_time = QDateTime.currentDateTime().addSecs(int(eta_sec)).toString("HH:mm:ss")
                display_text = f"%p% (剩余 {duration} | 预计 {finish_time} 结束)"
                self.progress_bar.setFormat(display_text)
                self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                self.progress_bar.setFormat("%p%")

        self.status_label.setText(f"发送中: {attempted}/{total}")

    def _calculate_eta_seconds(self, attempted: int, total: int) -> float:
        """从状态中提取配置，并调用纯数学方法计算 ETA"""
        if not self._state:
            return 0.0

        cfg = self._state.sender_config
        avg_normal = (cfg.min_delay + cfg.max_delay) / 2
        avg_rest = (cfg.rest_min + cfg.rest_max) / 2

        return self._math_calc_eta(
            attempted=attempted, 
            total=total, 
            burst_size=cfg.burst_size, 
            avg_normal=avg_normal, 
            avg_rest=avg_rest
        )

    @staticmethod
    def _math_calc_eta(attempted: int, total: int, burst_size: int, avg_normal: float, avg_rest: float) -> float:
        """
        计算剩余等待时间的纯数学辅助函数 (O(1))。

        契约 (Contract):
        1. 延时发生在发送动作之后，因此最后一条弹幕发完不产生延时，总延时次数为 total - 1。
        2. 延时的物理索引从 1 开始（第 k 条弹幕发完后的延时索引为 k）。
        3. 仅当延时索引能被 burst_size 整除时，触发大休息 (avg_rest)。
        """
        # 防御性校验：避免除零及负数异常
        if burst_size <= 0:
            burst_size = 1 

        # 统一处理 0 和 1 进度：
        # 准备开始(0)和准备发第1条(1)时，前面都没有发生过延时，
        # 其后续的延时索引区间都是 [1, total - 1]。
        current_k = max(1, attempted)
        remaining_waits = total - current_k

        if remaining_waits <= 0:
            return 0.0

        if burst_size == 1:
            return remaining_waits * avg_normal

        # 在闭区间 [current_k, total - 1] 中，计算能被 burst_size 整除的元素个数
        rest_count = (total - 1) // burst_size - (current_k - 1) // burst_size
        normal_count = remaining_waits - rest_count

        return (normal_count * avg_normal) + (rest_count * avg_rest)

    def _on_send_finished(self, sender_instance):
        """任务结束后的清理与保存逻辑"""
        # 恢复 UI
        self._reset_ui_after_task()

        if self.stop_event.is_set():
            self.status_label.setText("发送器：任务中止")
            self.progress_bar.setFormat("%p% (已停止)")
        else:
            self.status_label.setText("发送器：任务结束")
            self.progress_bar.setFormat("%p% (已完成)")

        # 检查是否有失败弹幕
        if sender_instance and sender_instance.unsent_danmakus:
            count = len(sender_instance.unsent_danmakus)
            reply = QMessageBox.question(
                self, "保存失败弹幕", 
                f"有 {count} 条弹幕发送失败。\n是否保存为新的 XML 文件以便重新发送？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
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

    def _update_btn_style(self, running: bool):
        """统一刷新按钮样式的私有方法"""
        state = "running" if running else "ready"
        self.start_btn.setProperty("state", state)
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)

    def _set_inputs_locked(self, locked: bool):
        """
        设置输入控件的锁定状态

        Args:
            locked (bool): True 表示锁定(不可编辑)，False 表示解锁(可编辑)。
        """
        self.basic_group.set_inputs_locked(locked)
        self.strategy_tabs.set_inputs_locked(locked)

    def _set_ui_for_task_start(self):
        """任务开始时的 UI 状态设置"""
        self._is_task_running = True
        self.stop_event.clear()

        # 按钮变红
        self.start_btn.setText("紧急停止")
        self._update_btn_style(True)

        # 锁定输入
        self._set_inputs_locked(True)

        # 重置进度
        self.log_output.clear()
        self.progress_bar.setValue(0)

    def _reset_ui_after_task(self):
        """任务结束后的 UI 状态复位"""
        self._is_task_running = False

        # 恢复按钮状态
        self.start_btn.setText("开始发送")
        self.start_btn.setEnabled(True)
        self._update_btn_style(False)

        # 解锁所有输入控件
        self._set_inputs_locked(False)

        # 重置进度条格式
        self.progress_bar.setFormat("%p%")


class BasicParamsGroup(QGroupBox):
    """基础参数区"""
    def __init__(self, parent=None):
        super().__init__("基础参数", parent)
        self._create_ui()

    def _create_ui(self):
        layout = QFormLayout(self)

        # BV号
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

        # 断点续传
        self.skip_sent_cb = QCheckBox("启用断点续传 (跳过已发送)")
        self.skip_sent_cb.setToolTip(
            "开启后，发送前会自动检查数据库。\n"
            "如果发现完全一致的弹幕（内容、时间、样式）已发送过，则自动跳过。"
        )

        layout.addRow(QLabel("视频BV号:"), bv_layout)
        layout.addRow(QLabel("分P选择:"), self.part_combo)
        layout.addRow(QLabel("弹幕文件:"), file_layout)
        layout.addRow(QLabel(""), self.skip_sent_cb)

    def bind_state(self, state: AppState):
        """将 UI 控件与 AppState 进行双向绑定"""
        UIBinder.bind(self.bv_input, state.video_state, "bvid", realtime=True)
        UIBinder.bind(self.skip_sent_cb, state.sender_config, "skip_sent")

        if state.video_state.selected_part_name:
            self.part_combo.setPlaceholderText(state.video_state.selected_part_name)

    def set_inputs_locked(self, locked: bool):
        """供主控调用的防误触锁"""
        enabled = not locked

        self.fetch_btn.setEnabled(enabled)
        self.file_btn.setEnabled(enabled)
        self.part_combo.setEnabled(enabled)
        self.bv_input.setReadOnly(locked)
        self.skip_sent_cb.setEnabled(enabled)


class StrategySettingsTabs(QTabWidget):
    """策略设置区"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._create_ui()

    def _create_ui(self):
        # Tab 1: 发送设置
        delay_tab = QWidget()
        delay_layout = QHBoxLayout(delay_tab)
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
        v_line.setFrameShape(QFrame.Shape.VLine)
        v_line.setFrameShadow(QFrame.Shadow.Sunken)
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
        self.addTab(delay_tab, "发送延迟")

                # Tab 2: 自动终止
        stop_tab = QWidget()
        stop_layout = QHBoxLayout(stop_tab)
        stop_layout.setContentsMargins(10, 20, 10, 20)

        # 数量限制
        stop_layout.addWidget(QLabel("已发送 >="))
        self.stop_count = QSpinBox()
        self.stop_count.setRange(0, 99999)
        stop_layout.addWidget(self.stop_count)
        stop_layout.addWidget(QLabel("条"))

        stop_layout.addSpacing(20)
        v_line2 = QFrame()
        v_line2.setFrameShape(QFrame.Shape.VLine)
        v_line2.setFrameShadow(QFrame.Shadow.Sunken)
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

        self.addTab(stop_tab, "自动终止")

    def bind_state(self, state: AppState):
        """将 UI 控件与 AppState 进行双向绑定"""
        config = state.sender_config

        # 发送延迟策略
        UIBinder.bind(self.min_delay, config, "min_delay")
        UIBinder.bind(self.max_delay, config, "max_delay")

        # 爆发模式
        UIBinder.bind(self.burst_size, config, "burst_size")
        UIBinder.bind(self.burst_rest_min, config, "rest_min")
        UIBinder.bind(self.burst_rest_max, config, "rest_max")

        # 自动终止规则
        UIBinder.bind(self.stop_count, config, "stop_after_count")
        UIBinder.bind(self.stop_time, config, "stop_after_time")
    
    def set_inputs_locked(self, locked: bool):
        """供主控调用的防误触锁"""
        enabled = not locked

        self.min_delay.setEnabled(enabled)
        self.max_delay.setEnabled(enabled)
        self.burst_size.setEnabled(enabled)
        self.burst_rest_min.setEnabled(enabled)
        self.burst_rest_max.setEnabled(enabled)
        self.stop_count.setEnabled(enabled)
        self.stop_time.setEnabled(enabled)