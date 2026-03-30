import logging

from PySide6.QtCore import QObject, Signal, QThreadPool, Slot

from ..framework.concurrency import GenericTask
from ...core.models.video import VideoInfo
from ...core.state import ApiAuthConfig
from ...core.services.video_fetcher import VideoFetcher
from ...api.bili_api_client import BiliApiClient


logger = logging.getLogger("App.System.Video")


# 用于后台批量获取的单例线程池
# 限制并发数为 1
_bg_fetch_pool = QThreadPool()
_bg_fetch_pool.setMaxThreadCount(1)
_bg_fetch_pool.setObjectName("BackgroundVideoFetchPool")


def _fetch_video_info(bvid: str, auth_config: ApiAuthConfig) -> VideoInfo:
    """业务函数: 获取视频信息"""
    with BiliApiClient.from_config(auth_config) as client:
        service = VideoFetcher(client)
        return service.fetch_info(bvid)


class VideoController(QObject):
    """
    视频业务控制器

    接管 UI 层的网络请求、线程调度，向 UI 层暴露纯粹的状态信号。
    """
    fetchStarted = Signal()
    fetchSucceeded = Signal(str, VideoInfo)  # bvid, VideoInfo
    fetchFailed = Signal(str, str)           # bvid, error_message

    def __init__(self, parent=None):
        super().__init__(parent)

    def fetch_info(self, bvid: str, auth_config: ApiAuthConfig, is_background: bool = False):
        """
        获取视频信息

        Args:
            bvid (str): 视频的 BV 号标识符。
            auth_config (ApiAuthConfig): API 认证配置，用于访问 Bilibili API。
            is_background (bool, optional): 是否在后台执行。默认为 False。
                - True: 在后台线程池中执行，不发送 fetchStarted 信号
                - False: 在全局线程池中执行，发送 fetchStarted 信号
        Signals:
            fetchStarted: 当 is_background 为 False 时发送，表示获取操作已启动。
            fetchSucceeded(str, VideoInfo): 获取成功时发送，参数为视频 BV 号和视频信息对象。
            fetchFailed(str, str): 获取失败时发送，参数为视频 BV 号和错误信息字符串。
        """
        if not is_background:
            self.fetchStarted.emit()

        task = GenericTask(_fetch_video_info, bvid, auth_config)

        @Slot(object)
        def _on_fetch_succeeded(info: VideoInfo):
            self.fetchSucceeded.emit(bvid, info)

        @Slot(str)
        def _on_fetch_failed(err_str: str):
            self.fetchFailed.emit(bvid, err_str)

        task.signals.result.connect(_on_fetch_succeeded)
        task.signals.error.connect(_on_fetch_failed)

        if is_background:
            _bg_fetch_pool.start(task)
        else:
            QThreadPool.globalInstance().start(task)