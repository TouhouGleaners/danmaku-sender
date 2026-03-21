import logging
import threading

from ..exceptions import BiliApiException
from ..database.history_manager import HistoryManager
from ..models.danmaku import Danmaku
from ..models.structs import VideoTarget
from ..services.danmaku_parser import DanmakuParser

from ...api.bili_api_client import BiliApiClient


class BiliDanmakuMonitor:
    """
    一个用于监视B站视频弹幕匹配情况的类。
    """
    def __init__(self, api_client: BiliApiClient, target: VideoTarget, interval: int = 60):
        """
        初始化监视器。

        Args:
            api_client: API 客户端
            target: 监视目标 (包含 cid, bvid, title)
            interval: 轮询间隔 (秒)
        """
        self.api_client = api_client
        self.target = target
        self.interval = interval

        self.danmaku_parser = DanmakuParser()
        self.history_manager = HistoryManager()
        self.logger = logging.getLogger("DanmakuMonitor")

    def _fetch_online_danmakus(self) -> list[Danmaku]:
        """获取在线弹幕列表"""
        try:
            xml_content = self.api_client.get_danmaku_list_xml(self.target.cid)
            return self.danmaku_parser.parse_xml_content(xml_content, is_online_data=True)
        except BiliApiException as e:
            self.logger.warning(f"获取在线弹幕失败: {e.message}")
            return []
        except Exception as e:
            self.logger.error(f"解析在线弹幕内容时发生错误: {e}")
            return []

    def run(self, stop_event: threading.Event, status_callback):
        """
        启动监视任务
        
        Args:
            stop_event: 停止信号
            status_callback: 状态回调函数，签名: (stats: dict) -> None
        """
        self.logger.info(f"🛡️ 监视启动: {self.target.display_string} | CID: {self.target.cid}")

        while not stop_event.is_set():
            try:
                online_danmakus = self._fetch_online_danmakus()
                
                if online_danmakus:
                    online_ids = [dm.dmid for dm in online_danmakus if dm.dmid]
                    
                    if online_ids:
                        verified_count = self.history_manager.verify_dmids(online_ids)
                        if verified_count > 0:
                            self.logger.info(f"✨ 核销成功: 确认了 {verified_count} 条新存活弹幕。")

                total, verified, lost = self.history_manager.get_stats(self.target.cid)
                
                pending = total - verified - lost
                if pending < 0:
                    pending = 0

                stats = {
                    'total': total,
                    'verified': verified,
                    'lost': lost,
                    'pending': pending
                }

                if status_callback:
                    status_callback(stats)

            except Exception as e:
                self.logger.error(f"监视循环发生异常: {e}", exc_info=True)

            if stop_event.wait(self.interval):
                self.logger.info("收到停止信号，监视任务终止。")
                break
            
        self.logger.info("弹幕监视器已退出")