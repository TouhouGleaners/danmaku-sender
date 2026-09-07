"""弹幕监视器 - 负责持续盯住某个 Target 并出统计指标"""

import logging

from .danmaku_verifier import DanmakuVerifier

from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.types.models.common import VideoTarget, MonitorStats


logger = logging.getLogger(__name__)


class BiliDanmakuMonitor:
    """
    弹幕监视器

    负责针对特定 VideoTarget 的持续监视周期管理。
    内部使用 DanmakuVerifier 执行核销操作。

    纯依赖注入设计：不管理连接生命周期，由调用方负责创建和注入依赖。
    """

    def __init__(self, verifier: DanmakuVerifier, target: VideoTarget, history_manager: HistoryManager):
        self.verifier = verifier
        self.target = target
        self.history_manager = history_manager

    def monitor(self, stats_baseline: float = 0.0) -> MonitorStats:
        """
        执行单次核销与统计。

        注意：监视过程中不标记丢失（mark_lost=False），因为发送队列可能还在进行中，
        B站弹幕分发有延迟，刚发送的弹幕可能还未进入弹幕池。丢失标记应由用户在历史记录页统一清算。

        Args:
            stats_baseline: 统计基线时间（秒），用于过滤历史数据

        Returns:
            MonitorStats: {'total': int, 'verified': int, 'pending': int, 'lost': int}

        Raises:
            BiliApiError: API 请求失败
            BiliNetworkError: 网络连接失败
        """
        # 使用 verifier 执行核销（不标记丢失，避免误杀刚发送的弹幕）
        verify_result = self.verifier.verify_cid(self.target.cid, mark_lost=False)

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
