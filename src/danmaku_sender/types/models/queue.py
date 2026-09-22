import uuid
from dataclasses import dataclass, field, replace
from enum import Enum, auto

from danmaku_sender.config import SenderConfig

from .common import VideoTarget
from .danmaku import Danmaku


class TaskStatus(Enum):
    """队列任务状态"""
    UNCONFIGURED = "未配置"
    PENDING = "等待中"
    RUNNING = "发送中"
    PAUSED = "已暂停"
    COMPLETED = "已完成"
    FAILED = "失败"
    SKIPPED = "已跳过"


class InsertPosition(Enum):
    """队列任务相对插入位置（相对参考任务）"""
    ABOVE = auto()
    BELOW = auto()


@dataclass(frozen=True)
class TaskSpec:
    """任务工单（入队后不可变）。

    Worker 只持有 TaskSpec / TaskSnapshot，摸不到 TaskRuntime。
    config 为入队/改单时的 model_copy 快照，入队后禁止再改其字段。
    danmakus 为 tuple，结构上不可替换；发送管线须持有自己的 Danmaku 副本
    （见 SendJob 构造处的 clone），不得回填 dmid 写穿本工单。
    """
    task_id: str
    target: VideoTarget
    danmakus: tuple[Danmaku, ...]
    config: SenderConfig
    p_index: int = 0
    p_title: str = ""
    xml_path: str = ""
    duration_ms: int = 0

    @property
    def total(self) -> int:
        return len(self.danmakus)


@dataclass
class TaskRuntime:
    """任务运行时（仅主线程 QueueState 可写）"""
    status: TaskStatus = TaskStatus.PENDING
    error_msg: str = ""
    attempted: int = 0


@dataclass
class TaskRecord:
    """QueueState 存储单元：不可变工单 + 可变运行时"""
    spec: TaskSpec
    runtime: TaskRuntime


@dataclass(frozen=True)
class TaskSnapshot:
    """Worker 启动时的一次性采样：status 在采样时定死，与后续主线程落账隔离。"""
    spec: TaskSpec
    status: TaskStatus


class TaskView:
    """任务只读视图（live 门面）。

    属性实时读自 TaskRecord，表格 refresh_row 无需换对象即可看到新值。
    禁止缓存字段值做业务判断，更禁止经此写入——变更一律走 QueueState API。
    """
    __slots__ = ("_record",)

    def __init__(self, record: TaskRecord) -> None:
        self._record = record

    @property
    def task_id(self) -> str:
        return self._record.spec.task_id

    @property
    def target(self) -> VideoTarget:
        return self._record.spec.target

    @property
    def danmakus(self) -> tuple[Danmaku, ...]:
        return self._record.spec.danmakus

    @property
    def config(self) -> SenderConfig:
        """配置副本。返回拷贝以防经只读视图改写队列配置（变更必须走 QueueState）。"""
        return self._record.spec.config.model_copy()

    @property
    def p_index(self) -> int:
        return self._record.spec.p_index

    @property
    def p_title(self) -> str:
        return self._record.spec.p_title

    @property
    def xml_path(self) -> str:
        return self._record.spec.xml_path

    @property
    def duration_ms(self) -> int:
        return self._record.spec.duration_ms

    @property
    def total(self) -> int:
        return self._record.spec.total

    @property
    def status(self) -> TaskStatus:
        return self._record.runtime.status

    @property
    def error_msg(self) -> str:
        return self._record.runtime.error_msg

    @property
    def attempted(self) -> int:
        return self._record.runtime.attempted

    def to_draft(self) -> "QueueTask":
        """拷贝为可变编辑沙盒（详情弹窗 / 构建弹窗用）"""
        spec = self._record.spec
        runtime = self._record.runtime
        return QueueTask(
            target=replace(spec.target),
            danmakus=list(spec.danmakus),
            config_snapshot=spec.config.model_copy(),
            task_id=spec.task_id,
            p_index=spec.p_index,
            p_title=spec.p_title,
            xml_path=spec.xml_path,
            duration_ms=spec.duration_ms,
            status=runtime.status,
            error_msg=runtime.error_msg,
            attempted=runtime.attempted,
        )

    def snapshot(self) -> TaskSnapshot:
        """定死当前 status 的不可变采样（Worker / 跨线程读取用）"""
        return TaskSnapshot(spec=self._record.spec, status=self._record.runtime.status)


@dataclass
class QueueTask:
    """构造期 / 编辑沙盒 DTO。

    仅用于「组装 → 入队」与「详情弹窗编辑」。入队后由 QueueState 拆成
    TaskSpec + TaskRuntime，本对象不再代表队列中的真实任务。
    """
    target: VideoTarget
    danmakus: list[Danmaku]
    config_snapshot: SenderConfig
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    p_index: int = 0
    p_title: str = ""
    xml_path: str = ""
    duration_ms: int = 0  # 视频时长（毫秒），用于弹幕时间越界校验
    status: TaskStatus = TaskStatus.PENDING
    error_msg: str = ""
    attempted: int = 0
    total: int = field(init=False)

    def __post_init__(self):
        self.total = len(self.danmakus)

    def validate(self) -> str | None:
        """验证任务数据合法性，返回错误信息，无错误返回 None"""
        if not self.target.bvid:
            return "缺少视频目标 (BVID)"
        if self.target.cid <= 0:
            return "未选择有效的分P"
        if not self.danmakus:
            return "未加载弹幕数据"
        return None

    def to_spec(self) -> TaskSpec:
        """打成不可变工单（深拷贝 target/config，弹幕收成 tuple）"""
        return TaskSpec(
            task_id=self.task_id,
            target=replace(self.target),
            danmakus=tuple(self.danmakus),
            config=self.config_snapshot.model_copy(),
            p_index=self.p_index,
            p_title=self.p_title,
            xml_path=self.xml_path,
            duration_ms=self.duration_ms,
        )
