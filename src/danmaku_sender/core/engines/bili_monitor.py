import logging

from ..models.exceptions import BiliApiError
from ..database.history_manager import HistoryManager
from ..models.danmaku import Danmaku
from ..models.structs import VideoTarget
from ..services.danmaku_parser import DanmakuParser

from ...api.bili_api_client import BiliApiClient


class BiliDanmakuMonitor:
    """
    弹幕监视核心引擎

    负责执行单次的网络请求与数据库比对
    """
    def __init__(self, api_client: BiliApiClient, target: VideoTarget):
        self.api_client = api_client
        self.target = target

        self.danmaku_parser = DanmakuParser()
        self.history_manager = HistoryManager()
        self.logger = logging.getLogger("DanmakuMonitor")

    def _fetch_online_danmakus(self) -> list[Danmaku]:
        """获取在线弹幕列表"""
        try:
            xml_content = self.api_client.get_danmaku_list_xml(self.target.cid)
            return self.danmaku_parser.parse_xml_content(xml_content, is_online_data=True)
        except BiliApiError as e:
            self.logger.warning(f"获取在线弹幕失败: {e.message}")
            return []
        except Exception as e:
            self.logger.error(f"解析在线弹幕内容时发生错误: {e}")
            return []

    def monitor(self, stats_baseline: float = 0.0) -> dict:
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
            'lost': lost,
            'pending': pending
        }