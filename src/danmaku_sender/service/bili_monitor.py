import logging
from contextlib import contextmanager

from .danmaku_parser import DanmakuParser

from danmaku_sender.repo.bili_api_client import BiliApiClient
from danmaku_sender.types.exceptions.exceptions import BiliApiError, BiliNetworkError
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.common import VideoTarget, MonitorStats, VerifyResult
from danmaku_sender.config import ApiAuthConfig


class BiliDanmakuMonitor:
    """
    弹幕监视核心引擎

    负责执行单次的网络请求与数据库比对。
    通过 context manager 工厂创建，自动管理 BiliApiClient 生命周期。
    """

    def __init__(self, api_client: BiliApiClient, target: VideoTarget, history_manager: HistoryManager):
        self.api_client = api_client
        self.target = target

        self.danmaku_parser = DanmakuParser()
        self.history_manager = history_manager
        self.logger = logging.getLogger(__name__)

    @staticmethod
    @contextmanager
    def create(target: VideoTarget, auth_config: ApiAuthConfig, history_manager: HistoryManager):
        """Context manager 工厂：自动管理 client 生命周期"""
        with BiliApiClient.from_config(auth_config) as client:
            yield BiliDanmakuMonitor(api_client=client, target=target, history_manager=history_manager)

    @classmethod
    def verify_by_cid(cls, cid: int, auth_config: ApiAuthConfig, history_manager: HistoryManager) -> VerifyResult:
        """
        轻量级单次验证：拉取指定 CID 的在线弹幕，核销存活并标记丢失。

        Returns:
            dict: {'verified': int, 'lost': int, 'total_checked': int}
        """
        logger = logging.getLogger(__name__)
        with BiliApiClient.from_config(auth_config) as client:
            try:
                xml_content = client.get_danmaku_list_xml(cid)
                parser = DanmakuParser()
                online_danmakus = parser.parse_xml_content(xml_content, is_online=True)
            except (BiliApiError, BiliNetworkError) as e:
                logger.warning(f"获取在线弹幕失败: {e}")
                raise
            except Exception as e:
                logger.error(f"解析在线弹幕内容时发生错误: {e}")
                raise

        online_dmids = [dm.dmid for dm in online_danmakus if dm.dmid]

        verified_count = 0
        if online_dmids:
            verified_count = history_manager.verify_dmids(online_dmids)

        history_manager.mark_as_lost(cid, online_dmids)
        total, verified, lost = history_manager.get_stats(cid)

        logger.info(f"[CID:{cid}] 验证完成: 核销 {verified_count} 条，标记丢失 {lost} 条，共检查 {len(online_dmids)} 条在线弹幕。")

        return {
            'verified': verified_count,
            'lost': lost,
            'total_checked': len(online_dmids),
        }

    @classmethod
    def verify_all_pending(cls, auth_config: ApiAuthConfig, history_manager: HistoryManager) -> VerifyResult:
        """
        批量验证所有含有待验证弹幕的 CID。

        Returns:
            dict: {'verified': int, 'lost': int, 'total_checked': int}
        """
        logger = logging.getLogger(__name__)
        pending_cids = history_manager.get_pending_cids()

        if not pending_cids:
            logger.info("没有待验证的弹幕记录。")
            return {'verified': 0, 'lost': 0, 'total_checked': 0}

        logger.info(f"开始批量验证，共 {len(pending_cids)} 个 CID 待检查。")

        total_verified = 0
        total_lost = 0

        for entry in pending_cids:
            cid = entry['cid']
            try:
                result = cls.verify_by_cid(cid, auth_config, history_manager)
                total_verified += result['verified']
                total_lost += result['lost']
            except Exception as e:
                logger.warning(f"CID {cid} 验证失败，跳过: {e}")

        logger.info(f"批量验证完成: 共核销 {total_verified} 条，标记丢失 {total_lost} 条，检查 {len(pending_cids)} 个 CID。")

        return {
            'verified': total_verified,
            'lost': total_lost,
            'total_checked': len(pending_cids),
        }

    def _fetch_online_danmakus(self) -> list[Danmaku]:
        """获取在线弹幕列表"""
        try:
            xml_content = self.api_client.get_danmaku_list_xml(self.target.cid)
            return self.danmaku_parser.parse_xml_content(xml_content, is_online=True)

        except (BiliApiError, BiliNetworkError) as e:
            self.logger.warning(f"获取在线弹幕失败: {e.message}")
            return []

        except Exception as e:
            self.logger.error(f"解析在线弹幕内容时发生错误: {e}")
            return []

    def monitor(self, stats_baseline: float = 0.0) -> MonitorStats:
        """执行单次核销与统计"""
        # 提取与核销
        online_danmakus = self._fetch_online_danmakus()
        online_dmids = [dm.dmid for dm in online_danmakus if dm.dmid]

        if online_dmids:
            verified_count = self.history_manager.verify_dmids(online_dmids)
            if verified_count > 0:
                self.logger.info(f"✨ 核销成功: 确认了 {verified_count} 条新存活弹幕。")

        # 传入基准时间，获取过滤后的数据
        total, verified, lost = self.history_manager.get_stats(self.target.cid, stats_baseline)

        pending = max(0, total - verified - lost)

        return {
            'total': total,
            'verified': verified,
            'pending': pending,
            'lost': lost
        }