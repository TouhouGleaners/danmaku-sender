import logging

from PySide6.QtCore import QObject, Signal, QThreadPool

from ..framework.task_runner import GenericTask
from ...api.bili_api_client import BiliApiClient
from ...core.state import ApiAuthConfig


logger = logging.getLogger("AuthController")


def _fetch_user_nav(auth_config: ApiAuthConfig) -> dict:
    """纯业务逻辑：调用 B 站 nav 接口获取用户信息"""
    with BiliApiClient.from_config(auth_config) as client:
        return client.get_user_info()


class AuthController(QObject):
    """用户授权与身份控制器"""
    user_info_received = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

    def refresh_user_info(self, auth_config: ApiAuthConfig):
        """发起异步请求刷新用户信息"""
        if not auth_config.sessdata:
            self.user_info_received.emit({"isLogin": False})
            return

        task = GenericTask(_fetch_user_nav, auth_config)
        task.signals.result.connect(self.user_info_received.emit)
        # 失败返回未登录状态
        task.signals.error.connect(lambda _: self.user_info_received.emit({"isLogin": False}))

        QThreadPool.globalInstance().start(task)