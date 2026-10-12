import logging

from PySide6.QtCore import QObject, QThreadPool, Signal, Slot

from danmaku_sender.config import ApiAuthConfig, NetworkPolicy, Settings
from danmaku_sender.infra.bilibili.bili_api_client import BiliApiClient
from danmaku_sender.service.video_fetcher import VideoFetcher
from danmaku_sender.state import AppState
from danmaku_sender.types.models.video import VideoInfo

from .concurrency import PoolTask

logger = logging.getLogger(__name__)


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

    def __init__(self, state: AppState, settings: Settings, parent=None):
        """初始化控制器。

        Args:
            state: 状态树聚合根，取活动会话的身份凭据。
            settings: 配置容器，取传输策略。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.state = state
        self.settings = settings

    def fetch_single_info(self, bvid: str, is_background: bool = False) -> None:
        """
        获取单条视频信息

        Args:
            bvid: 视频的 BV 号标识符。
            is_background: 是否在后台执行。为 True 时使用后台线程池且不发
                ``fetchStarted``；为 False 时使用全局线程池并发该信号。
        """
        if not is_background:
            self.fetchStarted.emit()

        session = self.state.session
        auth = ApiAuthConfig(sessdata=session.sessdata, bili_jct=session.bili_jct)
        network = NetworkPolicy(use_system_proxy=self.settings.global_config.use_system_proxy)
        task = PoolTask(self._task_fetch_info, bvid, auth, network)

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

    def fetch_multiple_infos(self, bvids: list[str]) -> None:
        """
        静默获取多条视频信息 (批量返回)

        调用此方法会自动进入后台专有队列，且享有 HTTP Keep-Alive 性能加成。

        Args:
            bvids: 视频的 BV 号标识符列表。
        """
        if not bvids:
            return

        session = self.state.session
        auth = ApiAuthConfig(sessdata=session.sessdata, bili_jct=session.bili_jct)
        network = NetworkPolicy(use_system_proxy=self.settings.global_config.use_system_proxy)
        task = PoolTask(self._task_fetch_infos, bvids, auth, network)

        @Slot(list)
        def _on_fetch_completed(results: list[tuple[str, VideoInfo | Exception]]):
            for bvid, result in results:
                if isinstance(result, Exception):
                    self.fetchFailed.emit(bvid, result)
                else:
                    self.fetchSucceeded.emit(bvid, result)

        task.signals.result.connect(_on_fetch_completed)
        _bg_fetch_pool.start(task)

    # ---- 后台任务 ----

    def _task_fetch_info(
        self,
        bvid: str,
        auth: ApiAuthConfig,
        network: NetworkPolicy,
    ) -> VideoInfo:
        """获取单条视频信息（后台线程执行）。

        Args:
            bvid: 视频的 BV 号标识符。
            auth: 身份凭据。
            network: 传输策略。

        Returns:
            视频信息。
        """
        with BiliApiClient(auth, network) as client:
            return VideoFetcher(client).fetch_info(bvid)

    def _task_fetch_infos(
        self,
        bvids: list[str],
        auth: ApiAuthConfig,
        network: NetworkPolicy,
    ) -> list[tuple[str, VideoInfo | Exception]]:
        """批量获取视频信息（后台线程执行）。

        Args:
            bvids: 视频的 BV 号标识符列表。
            auth: 身份凭据。
            network: 传输策略。

        Returns:
            每个 BV 号对应的视频信息或异常。
        """
        results = []
        with BiliApiClient(auth, network) as client:
            fetcher = VideoFetcher(client)
            for bvid in bvids:
                try:
                    results.append((bvid, fetcher.fetch_info(bvid)))
                except Exception as e:
                    results.append((bvid, e))
        return results
