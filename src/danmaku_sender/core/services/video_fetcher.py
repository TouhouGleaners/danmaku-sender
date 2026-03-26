import logging

from ..models.exceptions import BiliApiError
from ..models.video import VideoInfo, VideoPart

from ...api.bili_api_client import BiliApiClient


class VideoFetcher:
    """
    视频业务服务层
    负责协调 API 调用与数据转换
    """
    def __init__(self, api_client: BiliApiClient, logger: logging.Logger | None = None):
        self.client = api_client
        self.logger = logger if logger else logging.getLogger("App.System.Fetcher")

    def fetch_info(self, bvid: str) -> VideoInfo:
        """
        获取并解析视频信息

        Returns:
            VideoInfo 对象

        Raises:
            RuntimeError 当 API 失败或数据解析错误时
        """
        raw_data = self.client.get_video_info(bvid)

        parts = []
        raw_pages: list[dict] = raw_data.get('pages', [])

        if not raw_pages:
            self.logger.warning(f"视频 {bvid} 返回的分P列表为空。")

        for i, p in enumerate(raw_pages):
            cid = p.get('cid')
            if not cid:
                msg = f"解析错误: 第 {i+1} 个分P缺失关键字段 'cid'。"
                self.logger.error(msg)
                raise ValueError(msg)

            parts.append(VideoPart(
                cid=cid,
                page=p.get('page', i + 1),
                title=p.get('part', f"分P {i+1}"),
                duration=p.get('duration', 0)
            ))

        return VideoInfo(
            bvid=bvid,
            title=raw_data.get('title', '未知标题'),
            duration=raw_data.get('duration', 0),
            parts=parts
        )