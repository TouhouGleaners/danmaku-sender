"""弹幕核验服务 - 负责查在线、对库、标状态"""

import logging
from typing import Callable

from .danmaku_parser import DanmakuParser

from danmaku_sender.repo.bili_api_client import BiliApiClient
from danmaku_sender.types.exceptions.exceptions import BiliApiError, BiliNetworkError
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.types.models.common import VerifyResult


logger = logging.getLogger(__name__)


class DanmakuVerifier:
    """
    弹幕核验服务

    负责针对给定的 cid / dmids 执行拉取、比对、落库核销与标记丢失。
    无状态设计，每次操作都是独立的。
    """

    def __init__(self, api_client: BiliApiClient, history_manager: HistoryManager):
        self.api_client = api_client
        self.history_manager = history_manager
        self.parser = DanmakuParser()

    def verify_cid(self, cid: int, mark_lost: bool = True) -> VerifyResult:
        """
        验证单个 CID：拉取在线弹幕，核销存活并标记丢失。

        Args:
            cid: 视频分P的 CID
            mark_lost: 是否标记丢失（默认 True）

        Returns:
            VerifyResult: {'verified': int, 'lost': int, 'total_checked': int}

        Raises:
            BiliApiError: API 请求失败
            BiliNetworkError: 网络连接失败
        """
        try:
            xml_content = self.api_client.get_danmaku_list_xml(cid)
            online_danmakus = self.parser.parse_xml_content(xml_content, is_online=True)
        except (BiliApiError, BiliNetworkError) as e:
            logger.warning(f"[CID:{cid}] 获取在线弹幕失败: {e}")
            raise
        except Exception as e:
            logger.error(f"[CID:{cid}] 解析在线弹幕内容时发生错误: {e}")
            raise

        online_dmids = [dm.dmid for dm in online_danmakus if dm.dmid]

        verified_count = 0
        if online_dmids:
            verified_count = self.history_manager.verify_dmids(online_dmids)

        lost_count = 0
        if mark_lost:
            lost_count = self.history_manager.mark_as_lost(cid, online_dmids)

        logger.info(f"[CID:{cid}] 验证完成: 核销 {verified_count} 条，标记丢失 {lost_count} 条，共检查 {len(online_dmids)} 条在线弹幕。")

        return {
            'verified': verified_count,
            'lost': lost_count,
            'total_checked': len(online_dmids),
        }

    def verify_batch(
        self,
        cids: list[int],
        mark_lost: bool = True,
        on_progress: Callable[[int, int, VerifyResult], None] | None = None
    ) -> VerifyResult:
        """
        批量验证多个 CID。

        Args:
            cids: CID 列表
            mark_lost: 是否标记丢失（默认 True）
            on_progress: 进度回调 (已处理数, 总数, 本次增量结果)

        Returns:
            VerifyResult: {'verified': int, 'lost': int, 'total_checked': int}
        """
        if not cids:
            return {'verified': 0, 'lost': 0, 'total_checked': 0}

        logger.info(f"开始批量验证，共 {len(cids)} 个 CID 待检查。")

        total_verified = 0
        total_lost = 0
        total_checked = 0

        for i, cid in enumerate(cids):
            try:
                result = self.verify_cid(cid, mark_lost=mark_lost)
                total_verified += result['verified']
                total_lost += result['lost']
                total_checked += result['total_checked']
            except Exception as e:
                logger.warning(f"CID {cid} 验证失败，跳过: {e}")
                result: VerifyResult = {'verified': 0, 'lost': 0, 'total_checked': 0}

            # 进度回调（无论成功失败都调用，回调异常不中断批处理）
            if on_progress:
                try:
                    on_progress(i + 1, len(cids), result)
                except Exception as e:
                    logger.warning(f"进度回调执行失败，继续处理: {e}")

        logger.info(f"批量验证完成: 共核销 {total_verified} 条，标记丢失 {total_lost} 条，检查 {len(cids)} 个 CID，{total_checked} 条在线弹幕。")

        return {
            'verified': total_verified,
            'lost': total_lost,
            'total_checked': total_checked,
        }

    def get_online_dmids(self, cid: int) -> list[str]:
        """
        获取指定 CID 的在线弹幕 DMID 列表（不执行核销）。

        Args:
            cid: 视频分P的 CID

        Returns:
            list[str]: 在线弹幕的 DMID 列表

        Raises:
            BiliApiError: API 请求失败
            BiliNetworkError: 网络连接失败
        """
        try:
            xml_content = self.api_client.get_danmaku_list_xml(cid)
            online_danmakus = self.parser.parse_xml_content(xml_content, is_online=True)
            return [dm.dmid for dm in online_danmakus if dm.dmid]
        except (BiliApiError, BiliNetworkError) as e:
            logger.warning(f"[CID:{cid}] 获取在线弹幕失败: {e}")
            raise
        except Exception as e:
            logger.error(f"[CID:{cid}] 解析在线弹幕内容时发生错误: {e}")
            raise
