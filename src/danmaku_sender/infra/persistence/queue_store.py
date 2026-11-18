"""队列持久化存储：基于 queue.db 管理发送队列与发送进度。

数据分三张表保存：
- ``queue_task``：任务排序、目标视频、发送策略及当前进度与状态；
- ``queue_item``：任务关联的弹幕原始数据；
- ``queue_failure``：单条弹幕的发送失败记录及原因。

所有写入均以单事务执行，读写失败统一抛出 :class:`QueueStorageError`。
本模块假定由主线程独占调用，不支持多线程并发写入。
"""

import contextlib
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
from danmaku_sender.types.models.queue import TaskStatus

logger = logging.getLogger(__name__)

queue_db = DatabaseProxy()

_INSERT_BATCH = 100


class _QueueTask(Model):
    """queue_task ORM 模型：存储任务配置、队列顺序与当前状态。"""

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
    """queue_item ORM 模型：存储任务关联的弹幕数据。"""

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
    """queue_failure ORM 模型：存储单条弹幕的发送失败记录。"""

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
    """queue_item 的只读行数据：单条弹幕的发送参数。

    Attributes:
        idx (int): 在任务清单中的 0-based 索引。
        msg (str): 弹幕文本内容。
        progress (int): 弹幕出现时间（毫秒）。
        mode (int): 弹幕模式。
        fontsize (int): 弹幕字号。
        color (int): 弹幕十进制颜色值。
    """
    idx: int
    msg: str
    progress: int
    mode: int
    fontsize: int
    color: int


@dataclass(frozen=True)
class FailureRow:
    """queue_failure 的只读行数据：单条弹幕的发送失败记录。

    Attributes:
        idx (int): 在任务清单中的 0-based 索引。
        reason (str): 发送失败的原因说明。
    """
    idx: int
    reason: str


@dataclass(frozen=True)
class TaskRow:
    """queue_task 的只读行数据：任务配置、目标信息、排序与运行状态。

    这是数据库行的扁平映射，与任务的抽屉属于同一份信息的两种切法；
    抽屉模型接入后本类退场，扁平化只留在 SQL 翻译里。

    Attributes:
        task_id (str): 任务唯一标识。
        position (int): 队列顺序，数值越小越靠前。
        bvid (str | None): 目标视频 BVID；须与 cid 成对有值或同为 None。
        cid (int | None): 目标分P CID；须与 bvid 成对有值或同为 None。
        video_title (str): 视频标题。
        part_page (int | None): 分P序号（1-based）；未指定时为 None。
        part_title (str): 分P标题。
        duration_ms (int | None): 分P总时长（毫秒）；未知时为 None。
        source_path (str | None): 导入的弹幕文件路径；无文件来源时为 None。
        min_delay (float): 发送最小间隔（秒）。
        max_delay (float): 发送最大间隔（秒）。
        burst_enabled (bool): 是否启用爆发模式。
        burst_size (int): 爆发模式下每轮连续发送的条数。
        rest_min (float): 爆发模式每轮之间的最短休息时间（秒）。
        rest_max (float): 爆发模式每轮之间的最长休息时间（秒）。
        allow_duplicates (bool): 是否允许重复发送（为 True 时跳过查重）。
        status (TaskStatus): 当前任务状态；持久化时按枚举名存储。
        cursor (int): 断点续传游标，指向下一条待处理的弹幕索引。
        burst_count (int): 当前爆发周期内的已发条数计数。
        error (str | None): 任务失败或中止的原因；无错误时为 None。
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
    """queue.db 的数据访问入口。

    由主线程独占调用，负责任务与弹幕数据的持久化存取；
    所有数据库异常均转换为 :class:`QueueStorageError` 向上抛出。
    """

    def __init__(self, db_path: Path) -> None:
        """打开或创建队列数据库，并初始化所需数据表。

        Args:
            db_path (Path): queue.db 的文件路径。

        Raises:
            QueueStorageError: 数据库连接或建表失败。
        """
        self.db_path = str(db_path)
        try:
            queue_db.initialize(
                SqliteDatabase(self.db_path, pragmas={"journal_mode": "wal"}, check_same_thread=True)
            )
            queue_db.connect(reuse_if_open=True)
            queue_db.create_tables([_QueueTask, _QueueItem, _QueueFailure], safe=True)
        except Exception as e:
            # 清理未初始化完成的连接；清理过程中的异常不得掩盖原始错误
            with contextlib.suppress(Exception):
                if not queue_db.is_closed():
                    queue_db.close()
            logger.exception("队列库初始化失败 [%s]", self.db_path)
            raise QueueStorageError(f"队列库初始化失败 [{self.db_path}]", original_error=e) from e

    def save_task(self, row: TaskRow, items: Sequence[ItemRow] | None = None) -> None:
        """保存任务信息及可选的弹幕数据。

        根据 ``items`` 是否传入采用不同的更新策略：
        - ``items`` 为 None：仅更新任务配置、目标信息与队列顺序，保留库中既有的状态与进度；
        - ``items`` 不为 None：替换该任务的全部弹幕数据并清除既有失败记录，同时将状态与进度按 ``row`` 中的取值整体写入。

        仅在弹幕清单实际更换时传入 ``items``，纯配置或目标修改应传 None。

        Args:
            row (TaskRow): 待保存的任务行数据。
            items (Sequence[ItemRow] | None): 新的弹幕数据序列；为 None 时保留既有数据。

        Raises:
            QueueStorageError: 目标字段半配（bvid 与 cid 不成对），或数据库写入失败。
        """
        if (row.bvid is None) != (row.cid is None):
            raise QueueStorageError("目标半配：bvid 与 cid 必须成对有值或成对为空")
        try:
            with queue_db.atomic():
                spec = {
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
                state = {
                    "status": row.status.name,
                    "cursor": row.cursor,
                    "burst_count": row.burst_count,
                    "error": row.error,
                }
                # 更换弹幕数据时同步重置状态与进度，否则仅更新规格与队列顺序
                update_values = {"position": row.position, **spec, **state} if items is not None else {"position": row.position, **spec}
                (
                    _QueueTask
                        .insert(task_id=row.task_id, position=row.position, **spec, **state)
                        .on_conflict(
                            conflict_target=[_QueueTask.task_id],
                            update=update_values,
                        )
                        .execute()
                )
                if items is not None:
                    _QueueItem.delete().where(_QueueItem.task_id == row.task_id).execute()
                    _QueueFailure.delete().where(_QueueFailure.task_id == row.task_id).execute()
                    self._insert_items(row.task_id, items)
        except Exception as e:
            logger.exception("队列任务写入失败 [task_id=%s]", row.task_id)
            raise QueueStorageError(f"队列任务写入失败 [{row.task_id}]", original_error=e) from e

    def record_result(
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
        """在单事务内更新任务运行进度并记录单条弹幕的处理结果。

        当 ``failure_reason`` 为 None 时，表示该条已发送成功或被跳过，若此前存在同索引的失败记录则一并删除；否则按 ``idx`` 写入或覆盖对应的失败原因。

        Args:
            task_id (str): 任务唯一标识。
            idx (int): 本次处理对应的弹幕 0-based 索引。
            status (TaskStatus): 更新后的任务状态。
            cursor (int): 更新后的续传游标。
            burst_count (int): 更新后的爆发计数。
            error (str | None): 任务级错误说明；为 None 时清空既有错误。
            failure_reason (str | None): 该条弹幕的失败原因；为 None 时清除其失败记录。

        Raises:
            QueueStorageError: 指定任务不存在，或数据库写入失败。
        """
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
                    raise QueueStorageError(f"结果写入跳过：没有任务 [{task_id}] 的行")
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
            logger.exception("结果写入失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"结果写入失败 [{task_id}]", original_error=e) from e

    def update_task_state(
        self,
        task_id: str,
        *,
        status: TaskStatus,
        cursor: int,
        burst_count: int,
        error: str | None,
    ) -> None:
        """更新任务的运行状态与进度字段，用于暂停、终止、重置等任务级变更。

        所有状态字段均为必填参数，不设默认值；如需清空 ``error`` 须显式传入 None，以避免隐式默认值意外覆盖既有状态。

        Args:
            task_id (str): 任务唯一标识。
            status (TaskStatus): 目标任务状态。
            cursor (int): 目标续传游标。
            burst_count (int): 目标爆发计数。
            error (str | None): 错误或中止说明；传入 None 以清空。

        Raises:
            QueueStorageError: 指定任务不存在，或数据库写入失败。
        """
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
                raise QueueStorageError(f"状态写入跳过：没有任务 [{task_id}] 的行")
        except QueueStorageError:
            raise
        except Exception as e:
            logger.exception("队列状态写入失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"队列状态写入失败 [{task_id}]", original_error=e) from e

    def load_tasks(self) -> list[TaskRow]:
        """按队列顺序读取全部任务行。

        Returns:
            list[TaskRow]: 按 position 升序排列的任务行列表。

        Raises:
            QueueStorageError: 数据库读取或状态解析失败。
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
        """读取指定任务的全部弹幕数据，按原始索引升序排列。

        Args:
            task_id (str): 任务唯一标识。

        Returns:
            list[ItemRow]: 弹幕数据行列表。

        Raises:
            QueueStorageError: 数据库读取失败。
        """
        try:
            rows = _QueueItem.select().where(_QueueItem.task_id == task_id).order_by(_QueueItem.idx)
            return [
                ItemRow(idx=r.idx, msg=r.msg, progress=r.progress, mode=r.mode, fontsize=r.fontsize, color=r.color)
                for r in rows
            ]
        except Exception as e:
            logger.exception("弹幕数据读取失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"弹幕数据读取失败 [{task_id}]", original_error=e) from e

    def load_failures(self, task_id: str) -> list[FailureRow]:
        """读取指定任务的发送失败记录，按弹幕索引升序排列。

        Args:
            task_id (str): 任务唯一标识。

        Returns:
            list[FailureRow]: 失败记录行列表。

        Raises:
            QueueStorageError: 数据库读取失败。
        """
        try:
            rows = _QueueFailure.select().where(_QueueFailure.task_id == task_id).order_by(_QueueFailure.idx)
            return [FailureRow(idx=r.idx, reason=r.reason) for r in rows]
        except Exception as e:
            logger.exception("失败记录读取失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"失败记录读取失败 [{task_id}]", original_error=e) from e

    def reorder_tasks(self, task_ids: Sequence[str]) -> None:
        """按给定顺序重写全队列任务的 position，单事务执行。

        Args:
            task_ids (Sequence[str]): 重排后的任务标识序列，必须为当前队列任务的完整排列。

        Raises:
            QueueStorageError: 入参不是当前队列的完整排列，或数据库写入失败。
        """
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

    def delete_task(self, task_id: str) -> None:
        """删除指定任务及其关联的弹幕数据与失败记录，并紧缩剩余任务的顺序，单事务执行。

        Args:
            task_id (str): 待删除的任务唯一标识。

        Raises:
            QueueStorageError: 数据库删除或重排失败。
        """
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
        """关闭数据库连接。"""
        if not queue_db.is_closed():
            queue_db.close()

    @staticmethod
    def _insert_items(task_id: str, items: Sequence[ItemRow]) -> None:
        """分批写入弹幕数据，避免单次 SQLite 参数数量超出绑定上限。

        Args:
            task_id (str): 归属的任务唯一标识。
            items (Sequence[ItemRow]): 待插入的弹幕数据序列。
        """
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
