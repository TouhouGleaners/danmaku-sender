"""账号管理控制器：封装账号验证与用户信息获取的异步 API 调用"""
import logging

from PySide6.QtCore import QObject, Signal

from danmaku_sender.api.bili_api_client import BiliApiClient
from danmaku_sender.core.models.account import AccountCredential
from danmaku_sender.core.state import ApiAuthConfig
from danmaku_sender.ui.framework.concurrency import PoolTask


logger = logging.getLogger("App.System.Account")


def _check_login(config: ApiAuthConfig) -> bool:
    """检测账号登录状态"""
    try:
        with BiliApiClient.from_config(config) as client:
            nav = client.get_user_info()
            return bool(nav.get('isLogin'))
    except Exception:
        return False


def _fetch_user_info(config: ApiAuthConfig) -> dict | None:
    """获取用户详细信息"""
    try:
        with BiliApiClient.from_config(config) as client:
            return client.get_user_info()
    except Exception:
        return None


class AccountController(QObject):
    """账号管理控制器"""

    checkFinished = Signal(AccountCredential, bool)
    userInfoFetched = Signal(AccountCredential, object)  # dict | None

    def __init__(self, parent=None):
        super().__init__(parent)

    def check_account(self, account: AccountCredential, config: ApiAuthConfig):
        """异步检测账号是否有效"""
        PoolTask.submit(
            _check_login,
            lambda result: self.checkFinished.emit(account, result),
            lambda _: self.checkFinished.emit(account, False),
            config,
        )

    def fetch_user_info(self, account: AccountCredential, config: ApiAuthConfig):
        """异步获取用户信息（昵称、uid）"""
        PoolTask.submit(
            _fetch_user_info,
            lambda result: self.userInfoFetched.emit(account, result),
            lambda _: self.userInfoFetched.emit(account, None),
            config,
        )
