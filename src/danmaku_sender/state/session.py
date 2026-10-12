"""登录身份与账号列表。"""
from PySide6.QtCore import QObject, Signal

from danmaku_sender.types.models.account import AccountCredential


class SessionState(QObject):
    """登录身份与账号列表。

    Attributes:
        saved_accounts: 已保存的账号列表。
    """

    credentialsChanged = Signal()

    def __init__(self) -> None:
        """初始化会话状态。"""
        super().__init__()
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
