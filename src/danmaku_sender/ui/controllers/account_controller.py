"""账号管理控制器：封装账号验证与用户信息获取的异步 API 调用"""
import logging

from PySide6.QtCore import QObject, Signal

from danmaku_sender.api.bili_api_client import BiliApiClient
from danmaku_sender.types.models.account import AccountCredential
from danmaku_sender.types.models.user import UserProfile
from danmaku_sender.core.config import ApiAuthConfig
from danmaku_sender.runtime.app_state import AppState
from danmaku_sender.runtime.account_manager import AccountManager
from danmaku_sender.ui.framework.concurrency import PoolTask


logger = logging.getLogger("App.System.Account")


def _check_login(config: ApiAuthConfig) -> bool:
    """检测账号登录状态"""
    try:
        with BiliApiClient.from_config(config) as client:
            nav = client.get_user_info()
            return bool(nav.get('isLogin'))
    except Exception as e:
        logger.debug(f"账号检测失败: {e}")
        return False


def _fetch_user_info(config: ApiAuthConfig) -> dict | None:
    """获取用户详细信息"""
    try:
        with BiliApiClient.from_config(config) as client:
            return client.get_user_info()
    except Exception as e:
        logger.debug(f"获取用户信息失败: {e}")
        return None


class AccountController(QObject):
    """账号管理控制器"""

    checkFinished = Signal(AccountCredential, bool)
    userInfoFetched = Signal(AccountCredential, object)  # dict | None

    def __init__(self, parent=None):
        super().__init__(parent)

    @staticmethod
    def save_credentials(state: AppState, profile: UserProfile | None, account_manager: AccountManager):
        """同步 sessdata/bili_jct 到已保存账号列表并写盘"""
        if not state.sessdata or not state.bili_jct:
            return

        for acc in state.saved_accounts:
            if acc.sessdata == state.sessdata:
                acc.bili_jct = state.bili_jct
                if profile and profile.is_login:
                    acc.name = profile.username
                break
        else:
            acc = AccountCredential(sessdata=state.sessdata, bili_jct=state.bili_jct)
            if profile and profile.is_login:
                acc.name = profile.username
            state.saved_accounts.append(acc)

        account_manager.save_accounts(state.saved_accounts)
        if state.saved_accounts:
            logger.info(f"已保存 {len(state.saved_accounts)} 个账号。")

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
