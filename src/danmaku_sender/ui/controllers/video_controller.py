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
    with BiliApiClient.from_config(auth_config) as client:
        service = VideoFetcher(client)
        return service.fetch_info(bvid)

def _fetch_video_info_with_bvid(bvid: str, auth_config: ApiAuthConfig) -> tuple[str, VideoInfo]:
    return bvid, _fetch_video_info(bvid, auth_config)


class VideoController(QObject):
    """
    视频业务控制器

    接管 UI 层的网络请求、线程调度，向 UI 层暴露纯粹的状态信号。
    """
    fetchStarted = Signal()
    fetchSucceeded = Signal(VideoInfo)
    fetchFailed = Signal(str)

    # 历史记录后台信号
    bgFetchSucceeded = Signal(str, VideoInfo)  # bvid, VideoInfo
    bgFetchFailed = Signal(str, str)          # bvid, error_message

    def __init__(self, parent=None):
        super().__init__(parent)

    def fetch_info(self, bvid: str, auth_config: ApiAuthConfig):
        """前台: 高优先级获取 (发射器调用)"""
        # 立即通知 UI 切换到“加载中”状态
        self.fetchStarted.emit()

        # 将纯业务函数包装为跨线程任务
        task = GenericTask(_fetch_video_info, bvid, auth_config)

        # 桥接后台结果到控制器的对外信号
        task.signals.result.connect(self.fetchSucceeded.emit)
        task.signals.error.connect(self.fetchFailed.emit)

        # 扔进全局线程池
        QThreadPool.globalInstance().start(task)

    def fetch_info_background(self, bvid: str, auth_config: ApiAuthConfig):
        """后台: 低优先级排队获取 (历史页面调用)"""
        task = GenericTask(_fetch_video_info_with_bvid, bvid, auth_config)

        @Slot(object)
        def _on_result(res):
            ret_bvid, info = res
            self.bgFetchSucceeded.emit(ret_bvid, info)

        @Slot(str)
        def _on_error(err_str):
            self.bgFetchFailed.emit(bvid, err_str)

        task.signals.result.connect(_on_result)
        task.signals.error.connect(_on_error)

        _bg_fetch_pool.start(task)