import logging

from PySide6.QtCore import QObject, Signal, QThreadPool

from ..framework.task_runner import GenericTask
from ...core.models.video import VideoInfo
from ...core.state import ApiAuthConfig
from ...core.services.video_fetcher import VideoFetcher
from ...api.bili_api_client import BiliApiClient


logger = logging.getLogger("App.System.Video")


def _fetch_video_info(bvid: str, auth_config: ApiAuthConfig) -> VideoInfo:
    silent_logger = logging.getLogger("SilentWorker")
    silent_logger.propagate = False
    if not silent_logger.handlers:
        silent_logger.addHandler(logging.NullHandler())

    with BiliApiClient.from_config(auth_config, silent_logger) as client:
        service = VideoFetcher(client, logger=silent_logger)
        return service.fetch_info(bvid)


class VideoController(QObject):
    """
    视频业务控制器

    接管 UI 层的网络请求、线程调度，向 UI 层暴露纯粹的状态信号。
    """
    fetch_started = Signal()
    fetch_success = Signal(VideoInfo)
    fetch_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def fetch_info(self, bvid: str, auth_config: ApiAuthConfig):
        """外部 (UI) 调用的唯一入口"""
        # 立即通知 UI 切换到“加载中”状态
        self.fetch_started.emit()

        # 将纯业务函数包装为跨线程任务
        task = GenericTask(_fetch_video_info, bvid, auth_config)

        # 桥接后台结果到控制器的对外信号
        task.signals.result.connect(self.fetch_success.emit)
        task.signals.error.connect(self.fetch_error.emit)

        # 扔进全局线程池
        QThreadPool.globalInstance().start(task)