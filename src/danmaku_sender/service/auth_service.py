"""
认证服务层

封装 B 站用户认证相关的 API 操作，controller 层不直接接触 BiliApiClient。
纯依赖注入设计：不管理连接生命周期，由调用方负责创建和注入依赖。
"""

import logging

from danmaku_sender.repo.bili_api_client import BiliApiClient
from danmaku_sender.types.models.user import UserProfile


logger = logging.getLogger(__name__)


class AuthService:
    """
    B 站用户认证服务

    纯依赖注入设计：不管理连接生命周期，由调用方负责创建和注入依赖。
    """

    def __init__(self, api_client: BiliApiClient):
        self.client = api_client

    def fetch_user_profile(self) -> UserProfile:
        """获取当前登录用户的完整信息（含头像）"""
        nav_data = self.client.get_user_info()

        if not nav_data.get('isLogin'):
            return UserProfile(is_login=False, username="未登录")

        uid = nav_data.get('mid', 0)
        username = nav_data.get('uname', "未知用户")
        face_url = nav_data.get('face', "")

        avatar_data = b""
        if face_url:
            try:
                avatar_data = self.client.get_raw_resource(face_url)
            except Exception as e:
                logger.warning(f"下载头像失败 [URL: {face_url}]", exc_info=True)

        return UserProfile(is_login=True, username=username, uid=uid, avatar_bytes=avatar_data)

    def check_login(self) -> bool:
        """检测账号是否处于登录状态"""
        try:
            nav = self.client.get_user_info()
            return bool(nav.get('isLogin'))
        except Exception as e:
            logger.debug(f"账号检测失败: {e}")
            return False

    def fetch_raw_user_info(self) -> dict | None:
        """获取原始用户信息字典"""
        try:
            return self.client.get_user_info()
        except Exception as e:
            logger.debug(f"获取用户信息失败: {e}")
            return None
