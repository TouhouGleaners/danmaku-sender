import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal, QThreadPool

from ..framework.task_runner import GenericTask
from ...api.bili_api_client import BiliApiClient
from ...core.state import ApiAuthConfig


logger = logging.getLogger("AuthController")


@dataclass
class UserProfile:
    """同步交付的业务模型"""
    is_login: bool
    username: str
    avatar_bytes: bytes = b""


def _fetch_user_nav(auth_config: ApiAuthConfig) -> UserProfile:
    with BiliApiClient.from_config(auth_config) as client:
        try:
            # 用户信息
            nav_data = client.get_user_info()

            if not nav_data.get('isLogin'):
                return UserProfile(is_login=False, username="未登录")

            username = nav_data.get('uname', "未知用户")
            face_url = nav_data.get('face', "")

            # 下载头像
            avatar_data = b""
            if face_url:
                try:
                    avatar_data = client.get_raw_resource(face_url)
                except Exception as e:
                    logger.error(f"头像下载过程中发生非预期异常: {e}", exc_info=True)

            return UserProfile(is_login=True, username=username, avatar_bytes=avatar_data)

        except Exception as e:
            # 主流程失败
            logger.error(f"同步获取用户信息失败: {e}")
            raise


class AuthController(QObject):
    """用户授权与身份控制器"""
    user_profile_ready = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

    def refresh_user_info(self, auth_config: ApiAuthConfig):
        """发起异步请求刷新用户信息"""
        if not auth_config.sessdata:
            self.user_profile_ready.emit(UserProfile(False, "未登录"))
            return

        task = GenericTask(_fetch_user_nav, auth_config)
        task.signals.result.connect(self.user_profile_ready.emit)

        task.signals.error.connect(lambda _: self.user_profile_ready.emit(UserProfile(False, "未登录")))
        QThreadPool.globalInstance().start(task)