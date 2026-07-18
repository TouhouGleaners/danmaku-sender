import logging
import threading
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from .concurrency import WorkerThread, PoolTask
from .system_utils import KeepSystemAwake

from danmaku_sender.service.sender import SendPipeline, SendingContext, SendJob
from danmaku_sender.service.danmaku_parser import DanmakuParser
from danmaku_sender.service.danmaku_exporter import create_xml_from_danmakus
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.common import VideoTarget, UnsentDanmakusRecord
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.config import ApiAuthConfig, SenderConfig
from danmaku_sender.runtime.app_state import AppState


logger = logging.getLogger("App.Controller.Sender")


class SenderController(QObject):
    """发送任务业务控制器"""
    progressUpdated = Signal(int, int, float)
    taskFinished = Signal(object)
    xmlParsed = Signal(str, int)          # file_path, danmaku_count
    xmlParseFailed = Signal(str, object)  # file_path, raw_exception

    def __init__(self, state: AppState, history_manager: HistoryManager, parent=None):
        super().__init__(parent)
        self.state = state
        self.history_manager = history_manager
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
            stop_event=self._stop_event,
            history_manager=self.history_manager,
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
    """用于后台发送弹幕的线程（薄壳：仅负责线程生命周期与信号桥接）"""
    progressUpdated = Signal(int, int, float)  # 已尝试, 总数, ETA
    taskFinished = Signal(object)              # SendingContext

    def __init__(
        self,
        target: VideoTarget,
        danmakus: list[Danmaku],
        auth_config: ApiAuthConfig,
        strategy_config: SenderConfig,
        stop_event: threading.Event,
        history_manager: HistoryManager,
        parent=None
    ):
        super().__init__(parent)
        self.target = target
        self.danmakus = danmakus
        self.auth_config = auth_config
        self.strategy_config = strategy_config
        self.stop_event = stop_event
        self.history_manager = history_manager

    def run(self):
        ctx = None
        try:
            with KeepSystemAwake(self.strategy_config.prevent_sleep):
                pipeline = SendPipeline(self.auth_config, self.history_manager)
                job = SendJob(
                    target=self.target,
                    danmakus=self.danmakus,
                    config=self.strategy_config,
                    stop_event=self.stop_event,
                )
                ctx = pipeline.execute(job, progress_emitter=self.progressUpdated.emit)
        except Exception as e:
            self.report_error("任务发生严重错误", e)
        finally:
            self.taskFinished.emit(ctx)
