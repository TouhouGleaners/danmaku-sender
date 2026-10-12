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

    def upsert_account(self, sessdata: str, bili_jct: str, name: str | None = None) -> None:
        """登记或更新一个已保存账号。

        已存在同 ``sessdata`` 的账号则就地更新 ``bili_jct``，否则追加新条目。

        Args:
            sessdata: 账号的 SESSDATA，作为身份标识。
            bili_jct: 对应的 bili_jct。
            name: 昵称；为 None 时保留既有昵称。
        """
        if not sessdata or not bili_jct:
            return

        acc = next((a for a in self.saved_accounts if a.sessdata == sessdata), None)
        if acc:
            acc.bili_jct = bili_jct
        else:
            acc = AccountCredential(sessdata=sessdata, bili_jct=bili_jct)
            self.saved_accounts.append(acc)

        if name:
            acc.name = name
