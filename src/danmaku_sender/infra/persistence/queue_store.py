"""队列落盘：queue.db 的行存取，队列事实源的地基。

三张表，行契约按任务的抽屉落成真列：

- ``queue_task``：任务行——目标槽（bvid / cid / 标题 / 分P / 时长，成对有值或成对为空）、
  弹幕来源、发送策略（节奏与查重开关）、运行账热列（状态 / 游标 / 爆发相位 / 错误）与队列顺序；
- ``queue_item``：弹幕载荷行，只存载荷、不存状态——状态由游标与失败行表达，不记第二本账；
- ``queue_failure``：失败行（哪一条、为什么）。

写入分家，各成事务：

- ``save_task`` 写结构与顺序，运行账热列保持库中现值；带 items 即换清单（重新入账），
  载荷、游标、爆发相位、失败账同事务归零——结构与载荷永不出现半截配对；
- ``settle`` 逐条结算：热列与该条的失败账同事务落定，成功即清掉旧失败；
- ``update_state`` 只写热列（暂停 / 终止 / 重置这类不针对单条的变更）。

失败一律抛 :class:`QueueStorageError`，不吞错、不装成功。同一进程只允许一个活实例；
所有操作先验活体（身份比较），关闭或易主后的旧句柄一律拒绝。
"""

import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from peewee import (
    CharField,
    CompositeKey,
    DatabaseProxy,
    FloatField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
)

from danmaku_sender.types.exceptions.exceptions import QueueStorageError
from danmaku_sender.types.models.queue import TaskStatus

logger = logging.getLogger(__name__)

queue_db = DatabaseProxy()

_LIVE_LOCK = threading.Lock()

# insert_many 的参数上限按 SQLite 绑定数留余量：每行 7 个参数，每批 100 行
_INSERT_BATCH = 100


class _QueueTask(Model):
    """queue_task 表（模块内部）：任务行，结构列与热列同居一行、写入分家。"""

    task_id = CharField(primary_key=True)
    position = IntegerField()
    bvid = CharField(null=True)
    cid = IntegerField(null=True)
    video_title = CharField(default="")
    part_page = IntegerField(null=True)
    part_title = CharField(default="")
    duration_ms = IntegerField(null=True)
    source_path = TextField(null=True)
    min_delay = FloatField()
    max_delay = FloatField()
    burst_enabled = IntegerField()
    burst_size = IntegerField()
    rest_min = FloatField()
    rest_max = FloatField()
    allow_duplicates = IntegerField(default=0)
    status = CharField()
    cursor = IntegerField(default=0)
    burst_count = IntegerField(default=0)
    error = TextField(null=True)

    class Meta:
        table_name = "queue_task"
        database = queue_db


class _QueueItem(Model):
    """queue_item 表（模块内部）：弹幕载荷行，不存状态。"""

    task_id = CharField()
    idx = IntegerField()
    msg = TextField()
    progress = IntegerField()
    mode = IntegerField()
    fontsize = IntegerField()
    color = IntegerField()

    class Meta:
        table_name = "queue_item"
        database = queue_db
        primary_key = CompositeKey("task_id", "idx")
        indexes = ((("task_id",), False),)


class _QueueFailure(Model):
    """queue_failure 表（模块内部）：失败行。"""

    task_id = CharField()
    idx = IntegerField()
    reason = TextField()

    class Meta:
        table_name = "queue_failure"
        database = queue_db
        primary_key = CompositeKey("task_id", "idx")
        indexes = ((("task_id",), False),)


@dataclass(frozen=True)
class ItemRow:
    """queue_item 的一行：一条弹幕的载荷。

    Attributes:
        idx (int): 在任务清单中的下标。
        msg (str): 弹幕内容。
        progress (int): 出现时间（毫秒）。
        mode (int): 弹幕模式。
        fontsize (int): 字号。
        color (int): 颜色值。
    """
    idx: int
    msg: str
    progress: int
    mode: int
    fontsize: int
    color: int


@dataclass(frozen=True)
class FailureRow:
    """queue_failure 的一行：一条发送失败的账。

    Attributes:
        idx (int): 在任务清单中的下标。
        reason (str): 失败原因。
    """
    idx: int
    reason: str


@dataclass(frozen=True)
class TaskRow:
    """queue_task 的一行：任务的结构与运行账。

    Attributes:
        task_id (str): 任务标识。
        position (int): 队列顺序，小者在前。
        bvid (str | None): 目标视频 BVID；与 cid 成对有值或成对为空（为空即未指定目标）。
        cid (int | None): 目标分P CID。
        video_title (str): 视频标题。
        part_page (int | None): 第几 P（1-based）。
        part_title (str): 分P标题。
        duration_ms (int | None): 分P时长（毫秒）。
        source_path (str | None): 弹幕来自哪个文件。
        min_delay (float): 发包节奏：相邻两条的最小间隔（秒）。
        max_delay (float): 发包节奏：相邻两条的最大间隔（秒）。
        burst_enabled (bool): 发包节奏：是否启用爆发模式。
        burst_size (int): 发包节奏：爆发每轮连续发送的条数。
        rest_min (float): 发包节奏：爆发每轮之间的最短休息（秒）。
        rest_max (float): 发包节奏：爆发每轮之间的最长休息（秒）。
        allow_duplicates (bool): 允许重复发送（True 时不查重）。
        status (TaskStatus): 运行状态；落库取 ``status.name``，非法状态进不来。
        cursor (int): 续传游标，下一条待处理的弹幕下标。
        burst_count (int): 爆发相位计数。
        error (str | None): 失败或中止原因；None 表示没有错误。
    """
    task_id: str
    position: int
    bvid: str | None
    cid: int | None
    video_title: str = ""
    part_page: int | None = None
    part_title: str = ""
    duration_ms: int | None = None
    source_path: str | None = None
    min_delay: float = 0.0
    max_delay: float = 0.0
    burst_enabled: bool = False
    burst_size: int = 0
    rest_min: float = 0.0
    rest_max: float = 0.0
    allow_duplicates: bool = False
    status: TaskStatus = TaskStatus.PENDING
    cursor: int = 0
    burst_count: int = 0
    error: str | None = None


class QueueStore:
    """queue.db 的行存取入口；同一进程一个库、一个活实例。

    所有写入只有主线程调用（CLAUDE.md Rule 6）：状态写不存在乱序覆盖，
    过期写入追不上新检查点。
    """

    _live_owner: "QueueStore | None" = None

    def __init__(self, db_path: Path) -> None:
        """打开（或创建）队列库并确保三张表存在。

        Args:
            db_path: queue.db 的路径。

        Raises:
            QueueStorageError: 已有另一个队列库处于打开状态，或初始化失败。
        """
        self.db_path = str(db_path)
        with _LIVE_LOCK:
            if QueueStore._live_owner is not None:
                raise QueueStorageError(
                    f"同一进程只允许打开一个队列库：已有 [{QueueStore._live_owner.db_path}] 处于打开状态"
                )
            try:
                queue_db.initialize(SqliteDatabase(self.db_path))
                queue_db.connect(reuse_if_open=True)
                queue_db.create_tables([_QueueTask, _QueueItem, _QueueFailure], safe=True)
            except Exception as e:
                logger.exception("队列库初始化失败 [%s]", self.db_path)
                raise QueueStorageError(f"队列库初始化失败 [{self.db_path}]", original_error=e) from e
            QueueStore._live_owner = self

    def _ensure_live(self) -> None:
        """确认本实例仍是活实例（按身份比较）：关闭或易主后的旧句柄一律拒绝。"""
        if QueueStore._live_owner is not self:
            raise QueueStorageError(f"队列库句柄已失效 [{self.db_path}]")

    def save_task(self, row: TaskRow, items: Sequence[ItemRow] | None = None) -> None:
        """整任务写入（入队 / 编辑 / 换清单），结构与载荷同事务。

        只换结构时运行账热列保持库中现值——过期的结构保存不会让进度倒退。
        带 items 即换清单（重新入账）：载荷整份替换，游标、爆发相位、失败账
        同事务归零；仅在清单确实更换时传入 items，纯配置修改不要带。

        Args:
            row (TaskRow): 任务行（status / cursor / burst_count / error 仅新建行时生效）。
            items (Sequence[ItemRow] | None): 新的载荷行；None 表示不动载荷。

        Raises:
            QueueStorageError: 写入失败、目标半配，或句柄已失效。
        """
        self._ensure_live()
        if (row.bvid is None) != (row.cid is None):
            raise QueueStorageError("目标半配：bvid 与 cid 必须成对有值或成对为空")
        try:
            with queue_db.atomic():
                values = {
                    "position": row.position,
                    "bvid": row.bvid,
                    "cid": row.cid,
                    "video_title": row.video_title,
                    "part_page": row.part_page,
                    "part_title": row.part_title,
                    "duration_ms": row.duration_ms,
                    "source_path": row.source_path,
                    "min_delay": row.min_delay,
                    "max_delay": row.max_delay,
                    "burst_enabled": int(row.burst_enabled),
                    "burst_size": row.burst_size,
                    "rest_min": row.rest_min,
                    "rest_max": row.rest_max,
                    "allow_duplicates": int(row.allow_duplicates),
                }
                (
                    _QueueTask
                        .insert(
                            task_id=row.task_id,
                            status=row.status.name,
                            cursor=row.cursor,
                            burst_count=row.burst_count,
                            error=row.error,
                            **values,
                        )
                        .on_conflict(
                            conflict_target=[_QueueTask.task_id],
                            update=values,
                        )
                        .execute()
                )
                if items is not None:
                    _QueueTask.update(cursor=0, burst_count=0).where(_QueueTask.task_id == row.task_id).execute()
                    _QueueItem.delete().where(_QueueItem.task_id == row.task_id).execute()
                    _QueueFailure.delete().where(_QueueFailure.task_id == row.task_id).execute()
                    self._insert_items(row.task_id, items)
        except Exception as e:
            logger.exception("队列任务写入失败 [task_id=%s]", row.task_id)
            raise QueueStorageError(f"队列任务写入失败 [{row.task_id}]", original_error=e) from e

    def settle(
        self,
        task_id: str,
        idx: int,
        *,
        status: TaskStatus,
        cursor: int,
        burst_count: int,
        error: str | None,
        failure_reason: str | None,
    ) -> None:
        """逐条结算：热列与该条的失败账同事务落定。

        failure_reason 为 None 表示该条已发成或被跳过——若它曾有失败账，一并清掉；
        为字符串则记为该条的失败原因（同下标覆盖）。

        Args:
            task_id (str): 任务标识。
            idx (int): 本次结算的弹幕下标。
            status (TaskStatus): 运行状态。
            cursor (int): 续传游标。
            burst_count (int): 爆发相位计数。
            error (str | None): 失败或中止原因；显式传 None 即清空。
            failure_reason (str | None): 该条的失败原因；None 即清掉该条失败账。

        Raises:
            QueueStorageError: 写入失败，或没有该任务的行。
        """
        self._ensure_live()
        try:
            with queue_db.atomic():
                updated = (
                    _QueueTask
                        .update(
                            status=status.name, cursor=cursor, burst_count=burst_count, error=error
                        )
                        .where(_QueueTask.task_id == task_id)
                        .execute()
                )
                if updated == 0:
                    raise QueueStorageError(f"结算落账跳过：没有任务 [{task_id}] 的行")
                if failure_reason is None:
                    _QueueFailure.delete().where(
                        (_QueueFailure.task_id == task_id) & (_QueueFailure.idx == idx)
                    ).execute()
                else:
                    (
                        _QueueFailure
                            .insert(task_id=task_id, idx=idx, reason=failure_reason)
                            .on_conflict(
                                conflict_target=[_QueueFailure.task_id, _QueueFailure.idx],
                                update={_QueueFailure.reason: failure_reason},
                            )
                            .execute()
                    )
        except QueueStorageError:
            raise
        except Exception as e:
            logger.exception("结算落账失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"结算落账失败 [{task_id}]", original_error=e) from e

    def update_state(
        self,
        task_id: str,
        *,
        status: TaskStatus,
        cursor: int,
        burst_count: int,
        error: str | None,
    ) -> None:
        """只写运行账热列（暂停 / 终止 / 重置这类不针对单条的变更）。

        四个热列全为必填、无默认值：要清空 error 就显式传 None，
        不会出现「没传的字段被默认值冲掉」。

        Args:
            task_id (str): 任务标识。
            status (TaskStatus): 运行状态。
            cursor (int): 续传游标。
            burst_count (int): 爆发相位计数。
            error (str | None): 失败或中止原因；显式传 None 即清空。

        Raises:
            QueueStorageError: 写入失败，或没有该任务的行。
        """
        self._ensure_live()
        try:
            updated = (
                _QueueTask
                    .update(
                        status=status.name, cursor=cursor, burst_count=burst_count, error=error
                    )
                    .where(_QueueTask.task_id == task_id)
                    .execute()
            )
            if updated == 0:
                raise QueueStorageError(f"热列写入跳过：没有任务 [{task_id}] 的行")
        except QueueStorageError:
            raise
        except Exception as e:
            logger.exception("队列热列写入失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"队列热列写入失败 [{task_id}]", original_error=e) from e

    def load_tasks(self) -> list[TaskRow]:
        """按队列顺序读出全部任务行。

        Returns:
            list[TaskRow]: position 升序的任务行。

        Raises:
            QueueStorageError: 读取失败，或句柄已失效。
        """
        self._ensure_live()
        try:
            rows = _QueueTask.select().order_by(_QueueTask.position, _QueueTask.task_id)
            return [
                TaskRow(
                    task_id=r.task_id,
                    position=r.position,
                    bvid=r.bvid,
                    cid=r.cid,
                    video_title=r.video_title,
                    part_page=r.part_page,
                    part_title=r.part_title,
                    duration_ms=r.duration_ms,
                    source_path=r.source_path,
                    min_delay=r.min_delay,
                    max_delay=r.max_delay,
                    burst_enabled=bool(r.burst_enabled),
                    burst_size=r.burst_size,
                    rest_min=r.rest_min,
                    rest_max=r.rest_max,
                    allow_duplicates=bool(r.allow_duplicates),
                    status=TaskStatus[r.status],
                    cursor=r.cursor,
                    burst_count=r.burst_count,
                    error=r.error,
                )
                for r in rows
            ]
        except Exception as e:
            logger.exception("队列任务读取失败")
            raise QueueStorageError("队列任务读取失败", original_error=e) from e

    def load_items(self, task_id: str) -> list[ItemRow]:
        """读出一个任务的弹幕载荷行，按下标升序。

        Args:
            task_id (str): 任务标识。

        Returns:
            list[ItemRow]: 载荷行列表。

        Raises:
            QueueStorageError: 读取失败，或句柄已失效。
        """
        self._ensure_live()
        try:
            rows = _QueueItem.select().where(_QueueItem.task_id == task_id).order_by(_QueueItem.idx)
            return [
                ItemRow(idx=r.idx, msg=r.msg, progress=r.progress, mode=r.mode, fontsize=r.fontsize, color=r.color)
                for r in rows
            ]
        except Exception as e:
            logger.exception("弹幕载荷读取失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"弹幕载荷读取失败 [{task_id}]", original_error=e) from e

    def load_failures(self, task_id: str) -> list[FailureRow]:
        """读出一个任务的失败账，按下标升序。

        Args:
            task_id (str): 任务标识。

        Returns:
            list[FailureRow]: 失败行列表。

        Raises:
            QueueStorageError: 读取失败，或句柄已失效。
        """
        self._ensure_live()
        try:
            rows = _QueueFailure.select().where(_QueueFailure.task_id == task_id).order_by(_QueueFailure.idx)
            return [FailureRow(idx=r.idx, reason=r.reason) for r in rows]
        except Exception as e:
            logger.exception("失败账读取失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"失败账读取失败 [{task_id}]", original_error=e) from e

    def reorder(self, task_ids: Sequence[str]) -> None:
        """整队重排：按下标顺序重写 position，单事务；入参必须是当前队列的全排列。

        Args:
            task_ids (Sequence[str]): 重排后的 task_id 全排列。

        Raises:
            QueueStorageError: 入参不是全排列，或重排失败。
        """
        self._ensure_live()
        try:
            with queue_db.atomic():
                current = {r.task_id for r in _QueueTask.select(_QueueTask.task_id)}
                if len(task_ids) != len(current) or set(task_ids) != current:
                    raise QueueStorageError("队列重排拒绝：task_id 列表不是当前队列的全排列")
                for position, task_id in enumerate(task_ids):
                    _QueueTask.update(position=position).where(_QueueTask.task_id == task_id).execute()
        except QueueStorageError:
            raise
        except Exception as e:
            logger.exception("队列重排失败")
            raise QueueStorageError("队列重排失败", original_error=e) from e

    def delete(self, task_id: str) -> None:
        """删除一个任务的全部行（任务行、载荷、失败账），并压实剩余顺序，单事务。

        Args:
            task_id (str): 任务标识。

        Raises:
            QueueStorageError: 删除失败，或句柄已失效。
        """
        self._ensure_live()
        try:
            with queue_db.atomic():
                _QueueTask.delete().where(_QueueTask.task_id == task_id).execute()
                _QueueItem.delete().where(_QueueItem.task_id == task_id).execute()
                _QueueFailure.delete().where(_QueueFailure.task_id == task_id).execute()
                remaining = list(_QueueTask.select().order_by(_QueueTask.position, _QueueTask.task_id))
                for position, r in enumerate(remaining):
                    if r.position != position:
                        _QueueTask.update(position=position).where(_QueueTask.task_id == r.task_id).execute()
        except Exception as e:
            logger.exception("队列任务删除失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"队列任务删除失败 [{task_id}]", original_error=e) from e

    def close(self) -> None:
        """关闭数据库连接并释放活实例占用；非活实例调用无效果。"""
        with _LIVE_LOCK:
            if QueueStore._live_owner is not self:
                return
            if not queue_db.is_closed():
                queue_db.close()
            QueueStore._live_owner = None

    @staticmethod
    def _insert_items(task_id: str, items: Sequence[ItemRow]) -> None:
        """分批写入载荷行（每批有限行数，避开 SQLite 绑定参数上限）。"""
        for start in range(0, len(items), _INSERT_BATCH):
            chunk = items[start:start + _INSERT_BATCH]
            _QueueItem.insert_many(
                [
                    {
                        "task_id": task_id,
                        "idx": it.idx,
                        "msg": it.msg,
                        "progress": it.progress,
                        "mode": it.mode,
                        "fontsize": it.fontsize,
                        "color": it.color,
                    }
                    for it in chunk
                ]
            ).execute()
