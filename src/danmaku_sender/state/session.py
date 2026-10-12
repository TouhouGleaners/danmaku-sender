"""登录身份与账号列表。"""
from PySide6.QtCore import QObject, Signal

from danmaku_sender.config import ApiAuthConfig, Settings
from danmaku_sender.types.models.account import AccountCredential


class SessionState(QObject):
    """登录身份与账号列表。

    Attributes:
        saved_accounts: 已保存的账号列表。
    """

    credentialsChanged = Signal()

    def __init__(self, settings: Settings) -> None:
        """初始化会话状态。

        Args:
            settings: 持久化配置容器，供 ``get_api_auth`` 读取代理开关。
        """
        super().__init__()
        self._settings = settings
        self._sessdata: str = ""
        self._bili_jct: str = ""
        self.saved_accounts: list[AccountCredential] = []

    @property
    def sessdata(self) -> str:
        """B 站会话 Cookie SESSDATA。"""
        return self._sessdata

    @sessdata.setter
    def sessdata(self, value: str) -> None:
        if self._sessdata != value:
            self._sessdata = value
            self.credentialsChanged.emit()

    @property
    def bili_jct(self) -> str:
        """B 站会话 Cookie bili_jct。"""
        return self._bili_jct

    @bili_jct.setter
    def bili_jct(self, value: str) -> None:
        if self._bili_jct != value:
            self._bili_jct = value
            self.credentialsChanged.emit()

    def get_api_auth(self) -> ApiAuthConfig:
        """生成用于初始化客户端的 API 凭证对象。

        Returns:
            包含当前凭据与代理开关的 ``ApiAuthConfig``。
        """
        return ApiAuthConfig(
            sessdata=self.sessdata,
            bili_jct=self.bili_jct,
            use_system_proxy=self._settings.global_config.use_system_proxy,
        )
