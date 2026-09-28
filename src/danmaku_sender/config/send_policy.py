"""队列发送策略：一次队列运行共享，不随单个任务走。"""

from pydantic import Field

from .base import AtomicModel


class SendPolicy(AtomicModel):
    """队列发送策略（全局设置，可变）。

    描述「这个队列怎么跑」：

    - ``allow_duplicates``: 允许重复发送
        ——发送前不再比对数据库，已发出的弹幕会再次发送到视频上；
    - ``delay_between_tasks``: 相邻两个任务之间的间隔；
    - ``stop_after_count`` / ``stop_after_time``: 整个队列发到多少停。

    与 :class:`SenderConfig`（单个任务的发送节奏）分属不同层级。
    生命周期：**启动队列时取快照**，运行期间修改本对象不影响正在跑的
    队列（下次运行生效）；节奏则随任务入队时定死。
    """

    allow_duplicates: bool = False
    delay_between_tasks: float = Field(default=30.0, ge=0.0)
    stop_after_count: int = Field(default=0, ge=0)
    stop_after_time: int = Field(default=0, ge=0)
