"""账号管理控制器：封装账号验证与用户信息获取的异步 API 调用"""
import logging

from PySide6.QtCore import QObject, Signal

from .concurrency import PoolTask

from danmaku_sender.types.models.account import AccountCredential
from danmaku_sender.types.models.user import UserProfile
from danmaku_sender.config import ApiAuthConfig
from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.runtime.managers.account_manager import AccountManager
from danmaku_sender.service.auth_service import AuthService


logger = logging.getLogger("App.Controller.Account")


class AccountController(QObject):
    """账号管理控制器"""

    checkFinished = Signal(AccountCredential, bool)
    userInfoFetched = Signal(AccountCredential, object)  # dict | None

    def __init__(self, parent=None):
        super().__init__(parent)

    @staticmethod
    def save_credentials(state: AppState, profile: UserProfile | None, account_manager: AccountManager):
        """同步当前凭据到已保存账号列表并写盘"""
        if state.sessdata and state.bili_jct:
            acc = next((a for a in state.saved_accounts if a.sessdata == state.sessdata), None)
            if acc:
                acc.bili_jct = state.bili_jct
            else:
                acc = AccountCredential(sessdata=state.sessdata, bili_jct=state.bili_jct)
                state.saved_accounts.append(acc)

            if profile and profile.is_login:
                acc.name = profile.username

        account_manager.save_accounts(state.saved_accounts)
        if state.saved_accounts:
            logger.info(f"已保存 {len(state.saved_accounts)} 个账号。")

    def check_account(self, account: AccountCredential, config: ApiAuthConfig):
        """异步检测账号是否有效"""
        PoolTask.submit(
            AuthService.check_login,
            lambda result: self.checkFinished.emit(account, result),
            lambda _: self.checkFinished.emit(account, False),
            config,
        )

    def fetch_user_info(self, account: AccountCredential, config: ApiAuthConfig):
        """异步获取用户信息（昵称、uid）"""
        PoolTask.submit(
            AuthService.fetch_raw_user_info,
            lambda result: self.userInfoFetched.emit(account, result),
            lambda _: self.userInfoFetched.emit(account, None),
            config,
        )
