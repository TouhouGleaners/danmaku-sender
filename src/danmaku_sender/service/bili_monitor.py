"""弹幕监视器 - 负责持续盯住某个 Target 并出统计指标"""

import logging
from contextlib import contextmanager

from .danmaku_verifier import DanmakuVerifier
from .danmaku_parser import DanmakuParser

from danmaku_sender.repo.bili_api_client import BiliApiClient
from danmaku_sender.types.exceptions.exceptions import BiliApiError, BiliNetworkError
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.types.models.common import VideoTarget, MonitorStats, VerifyResult
from danmaku_sender.config import ApiAuthConfig


logger = logging.getLogger(__name__)


class BiliDanmakuMonitor:
    """
    弹幕监视器

    负责针对特定 VideoTarget 的持续监视周期管理。
    内部使用 DanmakuVerifier 执行核销操作。
    """

    def __init__(self, verifier: DanmakuVerifier, target: VideoTarget, history_manager: HistoryManager):
        self.verifier = verifier
        self.target = target
        self.history_manager = history_manager

    @staticmethod
    @contextmanager
    def create(target: VideoTarget, auth_config: ApiAuthConfig, history_manager: HistoryManager):
        """Context manager 工厂：自动管理 client 生命周期"""
        with BiliApiClient.from_config(auth_config) as client:
            verifier = DanmakuVerifier(api_client=client, history_manager=history_manager)
            yield BiliDanmakuMonitor(verifier=verifier, target=target, history_manager=history_manager)

    def monitor(self, stats_baseline: float = 0.0) -> MonitorStats:
        """
        执行单次核销与统计。

        Args:
            stats_baseline: 统计基线时间（秒），用于过滤历史数据

        Returns:
            MonitorStats: {'total': int, 'verified': int, 'pending': int, 'lost': int}

        Raises:
            BiliApiError: API 请求失败
            BiliNetworkError: 网络连接失败
        """
        # 使用 verifier 执行核销
        verify_result = self.verifier.verify_cid(self.target.cid, mark_lost=True)

        if verify_result['verified'] > 0:
            logger.info(f"✨ 核销成功: 确认了 {verify_result['verified']} 条新存活弹幕。")

        # 获取统计数据
        total, verified, lost = self.history_manager.get_stats(self.target.cid, stats_baseline)
        pending = max(0, total - verified - lost)

        return {
            'total': total,
            'verified': verified,
            'pending': pending,
            'lost': lost
        }

    @classmethod
    def verify_by_cid(cls, cid: int, auth_config: ApiAuthConfig, history_manager: HistoryManager) -> VerifyResult:
        """
        轻量级单次验证：拉取指定 CID 的在线弹幕，核销存活并标记丢失。

        Returns:
            VerifyResult: {'verified': int, 'lost': int, 'total_checked': int}
        """
        with BiliApiClient.from_config(auth_config) as client:
            verifier = DanmakuVerifier(api_client=client, history_manager=history_manager)
            return verifier.verify_cid(cid)

    @classmethod
    def verify_all_pending(cls, auth_config: ApiAuthConfig, history_manager: HistoryManager) -> VerifyResult:
        """
        批量验证所有含有待验证弹幕的 CID。

        Returns:
            VerifyResult: {'verified': int, 'lost': int, 'total_checked': int}
        """
        pending_cids = history_manager.get_pending_cids()

        if not pending_cids:
            logger.info("没有待验证的弹幕记录。")
            return {'verified': 0, 'lost': 0, 'total_checked': 0}

        cids = [entry['cid'] for entry in pending_cids]

        with BiliApiClient.from_config(auth_config) as client:
            verifier = DanmakuVerifier(api_client=client, history_manager=history_manager)
            return verifier.verify_batch(cids)
