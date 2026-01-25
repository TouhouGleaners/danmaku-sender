import logging

from ..models.video import VideoInfo, VideoPart
from ...api.bili_api_client import BiliApiClient


class VideoService:
    """
    视频业务服务层
    负责协调 API 调用与数据转换
    """
    def __init__(self, api_client: BiliApiClient):
        self.client = api_client

    def fetch_info(self, bvid: str) -> VideoInfo:
        """
        获取并解析视频信息

        Returns:
            VideoInfo 对象
        """
        raw_data = self.client.get_video_info(bvid)

        parts = []
        raw_pages: list[dict] = raw_data.get('pages', [])

        for p in raw_pages:
            parts.append(VideoPart(
                cid=p.get('cid', 0),
                page=p.get('page', 1),
                title=p.get('part', ''),
                duration=p.get('duration', 0)
            ))

        return VideoInfo(
            bvid=bvid,
            title=raw_data.get('title', '未知标题'),
            duration=raw_data.get('duration', 0),
            parts=parts
        )