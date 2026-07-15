"""
认证服务层

封装 B 站用户认证相关的 API 操作，controller 层不直接接触 BiliApiClient。
"""

import logging
from contextlib import contextmanager

from danmaku_sender.repo.bili_api_client import BiliApiClient
from danmaku_sender.types.exceptions.exceptions import BiliApiError
from danmaku_sender.types.models.user import UserProfile
from danmaku_sender.config import ApiAuthConfig


logger = logging.getLogger("App.Service.Auth")


class AuthService:
    """B 站用户认证服务"""

    @staticmethod
    def fetch_user_profile(auth_config: ApiAuthConfig) -> UserProfile:
        """获取当前登录用户的完整信息（含头像）"""
        with BiliApiClient.from_config(auth_config) as client:
            nav_data = client.get_user_info()

            if not nav_data.get('isLogin'):
                return UserProfile(is_login=False, username="未登录")

            uid = nav_data.get('mid', 0)
            username = nav_data.get('uname', "未知用户")
            face_url = nav_data.get('face', "")

            avatar_data = b""
            if face_url:
                try:
                    avatar_data = client.get_raw_resource(face_url)
                except Exception as e:
                    logger.warning(f"下载头像失败 [URL: {face_url}]", exc_info=True)

            return UserProfile(is_login=True, username=username, uid=uid, avatar_bytes=avatar_data)

    @staticmethod
    def check_login(auth_config: ApiAuthConfig) -> bool:
        """检测账号是否处于登录状态"""
        try:
            with BiliApiClient.from_config(auth_config) as client:
                nav = client.get_user_info()
                return bool(nav.get('isLogin'))
        except Exception as e:
            logger.debug(f"账号检测失败: {e}")
            return False

    @staticmethod
    def fetch_raw_user_info(auth_config: ApiAuthConfig) -> dict | None:
        """获取原始用户信息字典"""
        try:
            with BiliApiClient.from_config(auth_config) as client:
                return client.get_user_info()
        except Exception as e:
            logger.debug(f"获取用户信息失败: {e}")
            return None

    @staticmethod
    @contextmanager
    def qr_login_session(use_system_proxy: bool):
        """
        二维码登录会话上下文管理器。

        Yields:
            (client, qr_url, qrcode_key) — 登录客户端、二维码 URL、轮询 key
        """
        config = ApiAuthConfig(sessdata="", bili_jct="", use_system_proxy=use_system_proxy)
        with BiliApiClient.from_config(config) as client:
            data = client.generate_qr_code()
            url = data.get('url')
            qrcode_key = data.get('qrcode_key')

            if not url or not qrcode_key:
                raise BiliApiError(code=-1, message="获取二维码失败：B站接口返回异常")

            yield client, url, qrcode_key
