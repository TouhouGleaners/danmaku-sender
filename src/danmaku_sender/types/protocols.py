"""抽象接口定义，用于解耦 service 层与 repo 层的具体实现。"""

from typing import Protocol


class BiliApiProtocol(Protocol):
    """
    B站 API 客户端的抽象接口。

    service 层通过此协议与 repo 层的 BiliApiClient 交互，
    而不直接依赖具体实现，确保依赖方向为 service → types（而非 service → repo）。
    """

    def get_video_info(self, bvid: str) -> dict:
        """根据 BVID 获取视频详细信息"""
        ...

    def get_danmaku_list_xml(self, cid: int) -> str:
        """获取指定 CID 的线上实时弹幕 XML 内容"""
        ...

    def post_danmaku(self, cid: int, bvid: str, danmaku_params: dict) -> dict:
        """发送单条弹幕"""
        ...
