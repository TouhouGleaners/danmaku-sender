import logging
import threading
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from danmaku_sender.ui.framework.concurrency import WorkerThread, PoolTask

from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.service.sender import DanmakuScheduler, DanmakuExecutor, SendingContext, SendJob, DelayManager
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.result import DanmakuSendResult
from danmaku_sender.types.models.common import VideoTarget, UnsentDanmakusRecord
from danmaku_sender.config import ApiAuthConfig, SenderConfig
from danmaku_sender.runtime.app_state import AppState
from danmaku_sender.service.danmaku_parser import DanmakuParser
from danmaku_sender.service.danmaku_exporter import create_xml_from_danmakus
from danmaku_sender.repo.bili_api_client import BiliApiClient
from danmaku_sender.utils.system_utils import KeepSystemAwake


logger = logging.getLogger("App.System.SenderController")


class SenderController(QObject):
    """发送任务业务控制器"""
    progressUpdated = Signal(int, int, float)
    taskFinished = Signal(object)
    xmlParsed = Signal(str, int)          # file_path, danmaku_count
    xmlParseFailed = Signal(str, object)  # file_path, raw_exception

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self._worker: SendTaskWorker | None = None
        self._stop_event = threading.Event()

    def start_task(
        self,
        target: VideoTarget,
        danmakus: list[Danmaku],
        auth_config: ApiAuthConfig,
        strategy_config: SenderConfig
    ):
        """启动发送任务"""
        if self.is_running():
            logger.warning("任务已在运行中，无法重复启动。")
            return

        self._stop_event.clear()

        self._worker = SendTaskWorker(
            target=target,
            danmakus=danmakus,
            auth_config=auth_config,
            strategy_config=strategy_config,
            stop_event=self._stop_event
        )

        self._worker.progressUpdated.connect(self.progressUpdated.emit)
        self._worker.taskFinished.connect(self._on_worker_finished)

        self._worker.finished.connect(self._on_worker_cleanup)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def stop_task(self):
        """停止发送任务"""
        if self.is_running():
            self._stop_event.set()

    def is_running(self) -> bool:
        """检查任务是否正在运行"""
        return self._worker is not None and self._worker.isRunning()

    def is_stopped_manually(self) -> bool:
        """检查任务是否被手动中断"""
        return self._stop_event.is_set()

    def load_xml_file(self, file_path: str):
        """异步解析 XML 弹幕文件"""
        self.state.video_state.loaded_danmakus = []
        parser = DanmakuParser()
        PoolTask.submit(
            parser.parse_xml_file,
            lambda parsed: self._on_parse_success(parsed, file_path),
            lambda err: self._on_parse_error(err, file_path),
            file_path,
        )

    def export_unsent_xml(
        self,
        unsent_danmakus: list[UnsentDanmakusRecord],
        file_path: str,
        on_success: Callable[[None], None],
        on_error: Callable[[str], None],
    ):
        """异步保存未发送弹幕到 XML 文件"""
        PoolTask.submit(
            create_xml_from_danmakus,
            on_success,
            lambda err: on_error(str(err)),
            unsent_danmakus, file_path,
        )

    # region Slots

    @Slot(object)
    def _on_worker_finished(self, ctx):
        """内部槽函数：处理任务结束清理并向上传递"""
        self.taskFinished.emit(ctx)

    @Slot()
    def _on_worker_cleanup(self):
        """垃圾回收机制"""
        if self._worker is not None:
            logger.debug("SendTaskWorker 线程生命周期结束，正在清理控制器引用。")
            self._worker = None

    @Slot(list, str)
    def _on_parse_success(self, parsed: list, file_path: str):
        if parsed:
            self.state.video_state.loaded_danmakus = parsed
        self.xmlParsed.emit(file_path, len(parsed))

    @Slot(object, str)
    def _on_parse_error(self, err: Exception, file_path: str):
        self.xmlParseFailed.emit(file_path, err)

    # endregion


class SendTaskWorker(WorkerThread):
    """用于后台发送弹幕的线程"""
    progressUpdated = Signal(int, int, float)  # 已尝试, 总数, ETA
    taskFinished = Signal(object)              # SendingContext

    def __init__(
        self,
        target: VideoTarget,
        danmakus: list[Danmaku],
        auth_config: ApiAuthConfig,
        strategy_config: SenderConfig,
        stop_event: threading.Event,
        parent=None
    ):
        super().__init__(parent)
        self.logger = logging.getLogger("App.Sender.Worker")
        self.target = target
        self.danmakus = danmakus
        self.auth_config = auth_config
        self.strategy_config = strategy_config
        self.stop_event = stop_event
        self.sender_instance = None
        self.history_manager = HistoryManager()
        self.scheduler = None

    def run(self):
        ctx = None
        try:
            ctx = self._execute_pipeline()
        except Exception as e:
            self.report_error("任务发生严重错误", e)
        finally:
            if ctx:
                ctx.is_manually_stopped = self.stop_event.is_set()
                self._log_summary(ctx)
            self.taskFinished.emit(ctx)

    def _execute_pipeline(self):
        with (
            KeepSystemAwake(self.strategy_config.prevent_sleep),
            BiliApiClient.from_config(self.auth_config) as client
        ):
            executor = DanmakuExecutor(client)
            self.scheduler = DanmakuScheduler(executor, self.history_manager)

            job = SendJob(
                target=self.target,
                danmakus=self.danmakus,
                config=self.strategy_config,
                stop_event=self.stop_event,
                progress_callback=self._handle_job_progress,
                result_callback=self._handle_job_result
            )
            return self.scheduler.run_pipeline(job)

    def _handle_job_progress(self, attempted: int, total: int):
        avg_normal = (self.strategy_config.min_delay + self.strategy_config.max_delay) / 2
        avg_rest = (self.strategy_config.rest_min + self.strategy_config.rest_max) / 2

        eta_sec = DelayManager.calc_eta(
            attempted=attempted,
            total=total,
            burst_size=self.strategy_config.burst_size,
            avg_normal=avg_normal,
            avg_rest=avg_rest
        )

        self.progressUpdated.emit(attempted, total, eta_sec)

    def _handle_job_result(self, dm: Danmaku, result: DanmakuSendResult):
        if result.is_success and result.dmid:
            if not dm.dmid:
                dm.dmid = result.dmid
            self.history_manager.record_danmaku(self.target, dm, result.is_visible)

    def _log_summary(self, ctx: SendingContext):
        """日志输出"""
        self.logger.info("--- 发送任务结束 ---")
        if ctx.auto_stop_reason:
            self.logger.info(f"原因：{ctx.auto_stop_reason}")
        elif ctx.is_manually_stopped:
            self.logger.info("原因：任务被用户手动停止。")
        elif ctx.fatal_error_occurred:
            self.logger.critical("原因：任务因致命错误中断。请检查配置或网络！")
        else:
            self.logger.info("原因：所有弹幕已处理完毕。")

        self.logger.info(f"总计: {ctx.total} | 成功: {ctx.success_count} | 跳过: {ctx.skipped_count} | 失败: {ctx.attempted_count - ctx.success_count}")
