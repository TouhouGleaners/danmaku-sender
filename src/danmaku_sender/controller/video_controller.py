import logging

from PySide6.QtCore import QObject, Signal, QThreadPool, Slot

from danmaku_sender.types.models.video import VideoInfo
from danmaku_sender.config import ApiAuthConfig
from danmaku_sender.service.video_fetcher import VideoFetcher
from .concurrency import PoolTask


logger = logging.getLogger("App.Controller.Video")


# 使用独立单线程后台线程池处理批量获取任务，避免过度并发。
# 同时确保前台操作不被后台进程阻塞，以获得即时的资源分配。
_bg_fetch_pool = QThreadPool()
_bg_fetch_pool.setMaxThreadCount(1)
_bg_fetch_pool.setObjectName("BackgroundVideoFetchPool")


class VideoController(QObject):
    """
    视频业务控制器

    接管 UI 层的网络请求、线程调度，向 UI 层暴露纯粹的状态信号。
    """
    fetchStarted = Signal()
    fetchSucceeded = Signal(str, VideoInfo)  # bvid, VideoInfo
    fetchFailed = Signal(str, object)         # bvid, 异常对象

    def __init__(self, parent=None):
        super().__init__(parent)

    def fetch_single_info(self, bvid: str, auth_config: ApiAuthConfig, is_background: bool = False):
        """
        获取单条视频信息

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

        task = PoolTask(VideoFetcher.fetch_info_from_config, bvid, auth_config)

        @Slot(object)
        def _on_fetch_succeeded(info: VideoInfo):
            self.fetchSucceeded.emit(bvid, info)

        @Slot(object)
        def _on_fetch_failed(err: Exception):
            self.fetchFailed.emit(bvid, err)

        task.signals.result.connect(_on_fetch_succeeded)
        task.signals.error.connect(_on_fetch_failed)

        if is_background:
            _bg_fetch_pool.start(task)
        else:
            QThreadPool.globalInstance().start(task)

    def fetch_multiple_infos(self, bvids: list[str], auth_config: ApiAuthConfig):
        """
        静默获取多条视频信息 (批量返回)

        调用此方法会自动进入后台专有队列，且享有 HTTP Keep-Alive 性能加成。
        """
        if not bvids:
            return

        task = PoolTask(VideoFetcher.fetch_infos_from_config, bvids, auth_config)

        @Slot(list)
        def _on_fetch_completed(results: list[tuple[str, VideoInfo | Exception]]):
            for bvid, result in results:
                if isinstance(result, Exception):
                    self.fetchFailed.emit(bvid, result)
                else:
                    self.fetchSucceeded.emit(bvid, result)

        task.signals.result.connect(_on_fetch_completed)
        _bg_fetch_pool.start(task)