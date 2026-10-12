"""账号管理控制器：封装账号验证与用户信息获取的异步 API 调用"""
from PySide6.QtCore import QObject, Signal

from danmaku_sender.config import ApiAuthConfig, NetworkPolicy, Settings
from danmaku_sender.infra.bilibili.bili_api_client import BiliApiClient
from danmaku_sender.service.auth_service import AuthService
from danmaku_sender.types.models.account import AccountCredential

from .concurrency import PoolTask


class AccountController(QObject):
    """账号管理控制器。"""

    checkFinished = Signal(AccountCredential, bool)
    userInfoFetched = Signal(AccountCredential, object)  # dict | None

    def __init__(self, settings: Settings, parent=None):
        """初始化控制器。

        Args:
            settings: 配置容器，取传输策略。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.settings = settings

    def check_account(self, account: AccountCredential) -> None:
        """异步检测账号是否有效。

        Args:
            account: 待检测的已保存账号。
        """
        auth = ApiAuthConfig(sessdata=account.sessdata, bili_jct=account.bili_jct)
        network = NetworkPolicy(use_system_proxy=self.settings.global_config.use_system_proxy)
        PoolTask.submit(
            self._task_check_login,
            lambda result: self.checkFinished.emit(account, result),
            lambda _: self.checkFinished.emit(account, False),
            auth, network,
        )

    def fetch_user_info(self, account: AccountCredential) -> None:
        """异步获取用户信息（昵称、uid）。

        Args:
            account: 目标已保存账号。
        """
        auth = ApiAuthConfig(sessdata=account.sessdata, bili_jct=account.bili_jct)
        network = NetworkPolicy(use_system_proxy=self.settings.global_config.use_system_proxy)
        PoolTask.submit(
            self._task_fetch_user_info,
            lambda result: self.userInfoFetched.emit(account, result),
            lambda _: self.userInfoFetched.emit(account, None),
            auth, network,
        )

    # ---- 后台任务 ----

    def _task_check_login(self, auth: ApiAuthConfig, network: NetworkPolicy) -> bool:
        """检测账号是否有效（后台线程执行）。

        Args:
            auth: 身份凭据。
            network: 传输策略。

        Returns:
            账号是否有效。
        """
        with BiliApiClient(auth, network) as client:
            return AuthService(client).check_login()

    def _task_fetch_user_info(self, auth: ApiAuthConfig, network: NetworkPolicy) -> dict | None:
        """获取用户信息（后台线程执行）。

        Args:
            auth: 身份凭据。
            network: 传输策略。

        Returns:
            用户信息字典；失败返回 None。
        """
        with BiliApiClient(auth, network) as client:
            return AuthService(client).fetch_raw_user_info()
