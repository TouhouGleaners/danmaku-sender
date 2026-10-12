"""状态树聚合根。"""
from PySide6.QtCore import QObject, Signal

from .session import SessionState
from .workspace import WorkspaceState


class AppState(QObject):
    """状态树聚合根，仅承载易失状态。

    按切片访问：``state.session`` 为登录身份，``state.workspace`` 为会话工作区。
    持久化配置由 ``Runtime.settings`` 平级持有，二者生命周期不同。

    Attributes:
        session: 登录身份与账号列表。
        workspace: 会话工作区（队列与活动状态）。
    """

    configChanged = Signal()  # 配置被表单写回（自动落盘等副作用的广播点）

    def __init__(self) -> None:
        """初始化状态树。"""
        super().__init__()
        self.session = SessionState()
        self.workspace = WorkspaceState()
