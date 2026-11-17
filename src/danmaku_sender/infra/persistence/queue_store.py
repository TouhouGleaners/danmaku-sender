"""队列落盘：queue.db 的行存取，队列事实源的地基。

三张表，行契约按任务的抽屉落成真列：

- ``queue_task``：任务行——目标槽（bvid / cid / 标题 / 分P / 时长，bvid 为空即未指定目标）、
  弹幕来源、发送策略（节奏与查重开关）、运行账热列（状态 / 游标 / 爆发相位 / 错误）与队列顺序；
- ``queue_item``：弹幕载荷行，只存载荷、不存状态——状态由游标与失败行表达，不记第二本账；
- ``queue_failure``：失败行（哪一条、为什么）。

写入分家：``save_task`` 只写结构 / 顺序 / 载荷，``update_state`` 只写热列——
进度落账不会把刚改的配置盖回去，改配置也不会碰进度。
每次写入都在事务里；失败一律抛 :class:`QueueStorageError`，不吞错、不装成功。
"""

import logging
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

logger = logging.getLogger(__name__)

queue_db = DatabaseProxy()


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
        bvid (str | None): 目标视频 BVID；为空即未指定目标（cid 同为空）。
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
        status (str): 运行状态名。
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
    status: str = "PENDING"
    cursor: int = 0
    burst_count: int = 0
    error: str | None = None


class QueueStore:
    """queue.db 的行存取入口。

    同一进程只允许打开一个队列库（模块级连接与 history_manager 同款姿势）：
    第二个不同路径的实例会被拒绝，防止两条连接互写同一个代理。
    只有主线程写入（CLAUDE.md Rule 6）：状态写不存在乱序覆盖，
    过期的热列更新不会追上新的检查点。
    """

    _live_path: str | None = None

    def __init__(self, db_path: Path) -> None:
        """打开（或创建）队列库并确保三张表存在。

        Args:
            db_path: queue.db 的路径。

        Raises:
            QueueStorageError: 已有另一个队列库处于打开状态，或初始化失败。
        """
        self.db_path = db_path
        if QueueStore._live_path is not None:
            raise QueueStorageError(
                f"同一进程只允许打开一个队列库：已有 [{QueueStore._live_path}] 处于打开状态"
            )
        try:
            queue_db.initialize(SqliteDatabase(str(db_path)))
            queue_db.connect(reuse_if_open=True)
            queue_db.create_tables([_QueueTask, _QueueItem, _QueueFailure], safe=True)
        except Exception as e:
            logger.exception("队列库初始化失败 [%s]", db_path)
            raise QueueStorageError(f"队列库初始化失败 [{db_path}]", original_error=e) from e
        QueueStore._live_path = str(db_path)

    def save_task(self, row: TaskRow, items: Sequence[ItemRow]) -> None:
        """整任务的结构写入（入队 / 编辑 / 换清单）：一行 + 整份载荷，单事务。

        只写结构 / 顺序 / 载荷，运行账热列保持库中现值——过期的结构保存
        不会让进度倒退。同 task_id 覆盖；换清单即整份替换载荷行。

        Args:
            row (TaskRow): 任务行（status / cursor / burst_count / error 仅在新建行时落初值）。
            items (Sequence[ItemRow]): 弹幕载荷行，按下标写入。

        Raises:
            QueueStorageError: 写入失败。
        """
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
                        status=row.status,
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
                _QueueItem.delete().where(_QueueItem.task_id == row.task_id).execute()
                if items:
                    _QueueItem.insert_many(
                        [
                            {
                                "task_id": row.task_id,
                                "idx": it.idx,
                                "msg": it.msg,
                                "progress": it.progress,
                                "mode": it.mode,
                                "fontsize": it.fontsize,
                                "color": it.color,
                            }
                            for it in items
                        ]
                    ).execute()
        except Exception as e:
            logger.exception("队列任务写入失败 [task_id=%s]", row.task_id)
            raise QueueStorageError(f"队列任务写入失败 [{row.task_id}]", original_error=e) from e

    def update_state(
        self,
        task_id: str,
        *,
        status: str,
        cursor: int,
        burst_count: int,
        error: str | None,
    ) -> None:
        """只写运行账热列（逐条结算 / 状态变更用），结构与载荷原样不动。

        四个热列全为必填、无默认值：要清空 error 就显式传 None，
        不会出现「没传的字段被默认值冲掉」。

        Args:
            task_id (str): 任务标识。
            status (str): 运行状态名。
            cursor (int): 续传游标。
            burst_count (int): 爆发相位计数。
            error (str | None): 失败或中止原因；显式传 None 即清空。

        Raises:
            QueueStorageError: 写入失败，或没有该任务的行。
        """
        try:
            updated = (
                _QueueTask
                .update(status=status, cursor=cursor, burst_count=burst_count, error=error)
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

    def add_failure(self, task_id: str, failure: FailureRow) -> None:
        """记一条失败账（逐条结算用）；同下标覆盖。

        Args:
            task_id (str): 任务标识。
            failure (FailureRow): 失败行。

        Raises:
            QueueStorageError: 写入失败。
        """
        try:
            with queue_db.atomic():
                (
                    _QueueFailure
                    .insert(task_id=task_id, idx=failure.idx, reason=failure.reason)
                    .on_conflict(
                        conflict_target=[_QueueFailure.task_id, _QueueFailure.idx],
                        update={_QueueFailure.reason: failure.reason},
                    )
                    .execute()
                )
        except Exception as e:
            logger.exception("失败账写入失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"失败账写入失败 [{task_id}]", original_error=e) from e

    def load_tasks(self) -> list[TaskRow]:
        """按队列顺序读出全部任务行。

        Returns:
            list[TaskRow]: position 升序的任务行。

        Raises:
            QueueStorageError: 读取失败。
        """
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
                    status=r.status,
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
            QueueStorageError: 读取失败。
        """
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
            QueueStorageError: 读取失败。
        """
        try:
            rows = _QueueFailure.select().where(_QueueFailure.task_id == task_id).order_by(_QueueFailure.idx)
            return [FailureRow(idx=r.idx, reason=r.reason) for r in rows]
        except Exception as e:
            logger.exception("失败账读取失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"失败账读取失败 [{task_id}]", original_error=e) from e

    def reorder(self, task_ids: Sequence[str]) -> None:
        """整队重排：按下标顺序重写 position，单事务。

        Args:
            task_ids (Sequence[str]): 重排后的 task_id 全排列。

        Raises:
            QueueStorageError: 重排失败。
        """
        try:
            with queue_db.atomic():
                for position, task_id in enumerate(task_ids):
                    _QueueTask.update(position=position).where(_QueueTask.task_id == task_id).execute()
        except Exception as e:
            logger.exception("队列重排失败")
            raise QueueStorageError("队列重排失败", original_error=e) from e

    def delete(self, task_id: str) -> None:
        """删除一个任务的全部行（任务行、载荷、失败账），单事务；不存在时静默返回。

        Args:
            task_id (str): 任务标识。

        Raises:
            QueueStorageError: 删除失败。
        """
        try:
            with queue_db.atomic():
                _QueueTask.delete().where(_QueueTask.task_id == task_id).execute()
                _QueueItem.delete().where(_QueueItem.task_id == task_id).execute()
                _QueueFailure.delete().where(_QueueFailure.task_id == task_id).execute()
        except Exception as e:
            logger.exception("队列任务删除失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"队列任务删除失败 [{task_id}]", original_error=e) from e

    def close(self) -> None:
        """关闭数据库连接并释放单实例占用。"""
        if not queue_db.is_closed():
            queue_db.close()
        QueueStore._live_path = None
