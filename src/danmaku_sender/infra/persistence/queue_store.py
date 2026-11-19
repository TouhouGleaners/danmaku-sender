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
import time
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
    fn,
)

from danmaku_sender.types.exceptions.exceptions import QueueStorageError
from danmaku_sender.types.models.common import TaskMeta, VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import (
    Task,
    TaskConfig,
    TaskDefinition,
    TaskExecution,
    TaskStatus,
)
from danmaku_sender.utils.file_utils import backup_corrupt_file

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

    作为数据表行的扁平映射类型使用，待队列领域模型统一后由领域类型直接替代。

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

    @classmethod
    def open_with_recovery(cls, db_path: Path) -> "QueueStore":
        """打开队列数据库并执行一次全量读取校验。

        若数据库文件损坏或无法读取，先关闭连接并将主库及 WAL 附属文件备份，随后创建空库重新打开；
        若重建后仍无法打开，则向上抛出异常。

        Args:
            db_path (Path): queue.db 的文件路径。

        Returns:
            QueueStore: 可用的队列存储实例。

        Raises:
            QueueStorageError: 备份重建后仍无法打开数据库。
        """
        store: QueueStore | None = None
        try:
            store = cls(db_path)
            store.load_all()
            return store
        except QueueStorageError:
            if store is not None:
                store.close()
            if not cls._looks_corrupt(db_path):
                raise
            logger.exception("队列库已损坏，备份后以空库启动 [%s]", db_path)
            cls._backup_corrupt(db_path)
            return cls(db_path)

    @staticmethod
    def _looks_corrupt(db_path: Path) -> bool:
        """判断库文件是否已不是 SQLite 格式（被截断或覆盖写坏）。

        文件头是 SQLite 格式的不在此列——读不动更可能是临时锁定或 IO 故障，
        这种情况保留原文件并向上抛出，不按损坏处理。

        Args:
            db_path (Path): queue.db 的文件路径。

        Returns:
            bool: 文件存在且不是 SQLite 格式时返回 True。
        """
        try:
            with open(db_path, "rb") as fh:
                return fh.read(16) != b"SQLite format 3\x00"
        except OSError:
            return False

    @staticmethod
    def _backup_corrupt(db_path: Path) -> None:
        """备份损坏的数据库文件及其 WAL / SHM 附属文件。

        备份后缀包含精确时间戳，避免多次损坏时与既有备份文件冲突，
        同时防止新建同路径数据库时重放遗留的 WAL 日志。

        Args:
            db_path (Path): queue.db 的文件路径。

        Raises:
            QueueStorageError: 任一待备份文件仍在原地（改名失败），无法安全重建。
        """
        stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns()}"
        for suffix in ("", "-wal", "-shm"):
            path = db_path.parent / f"{db_path.name}{suffix}"
            if path.exists() and backup_corrupt_file(path, suffix=f".corrupt-{stamp}") is None:
                raise QueueStorageError(f"无法备份损坏的队列库 [{path}]")

    def add_task(self, task: Task) -> None:
        """将新任务追加至队列末尾，连同弹幕数据一并写入，单事务执行。

        Args:
            task (Task): 待入队的任务。

        Raises:
            QueueStorageError: 目标字段不成对或数据库写入失败。
        """
        try:
            with queue_db.atomic():
                _QueueTask.insert(**self._row_values(task, self._next_position())).execute()
                self._insert_items(task.definition.task_id, task.definition.danmakus)
        except Exception as e:
            logger.exception("队列任务写入失败 [task_id=%s]", task.definition.task_id)
            raise QueueStorageError(f"队列任务写入失败 [{task.definition.task_id}]", original_error=e) from e

    def insert_task(self, task: Task, at: int) -> None:
        """将新任务插入指定位置，后续任务依次后移，单事务执行。

        Args:
            task (Task): 待入队的任务。
            at (int): 插入位置（0-based 索引）；等于当前队列长度时等价于追加至末尾。

        Raises:
            QueueStorageError: 目标字段不成对或数据库写入失败。
        """
        try:
            with queue_db.atomic():
                for r in _QueueTask.select().where(_QueueTask.position >= at):
                    _QueueTask.update(position=r.position + 1).where(_QueueTask.task_id == r.task_id).execute()
                _QueueTask.insert(**self._row_values(task, at)).execute()
                self._insert_items(task.definition.task_id, task.definition.danmakus)
        except Exception as e:
            logger.exception("队列任务插入失败 [task_id=%s]", task.definition.task_id)
            raise QueueStorageError(f"队列任务插入失败 [{task.definition.task_id}]", original_error=e) from e

    def update_task(self, task: Task, *, items_replaced: bool = False) -> None:
        """更新既有任务的配置、目标与运行状态，保持原队列位置不变。

        当 ``items_replaced`` 为 True 时，同步替换该任务的全部弹幕数据并清除既有失败记录；
        为 False 时仅更新任务行属性，保留既有弹幕与失败记录。

        Args:
            task (Task): 更新后的任务。
            items_replaced (bool): 是否同时替换弹幕列表。

        Raises:
            QueueStorageError: 任务不存在、目标字段不成对或数据库写入失败。
        """
        task_id = task.definition.task_id
        try:
            with queue_db.atomic():
                old = _QueueTask.get_or_none(_QueueTask.task_id == task_id)
                if old is None:
                    raise QueueStorageError(f"任务更新跳过：没有任务 [{task_id}] 的行")
                _QueueTask.update(**self._row_values(task, old.position)).where(_QueueTask.task_id == task_id).execute()
                if items_replaced:
                    _QueueItem.delete().where(_QueueItem.task_id == task_id).execute()
                    _QueueFailure.delete().where(_QueueFailure.task_id == task_id).execute()
                    self._insert_items(task_id, task.definition.danmakus)
        except QueueStorageError:
            raise
        except Exception as e:
            logger.exception("队列任务更新失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"队列任务更新失败 [{task_id}]", original_error=e) from e

    def reissue_task(self, old_task_id: str, task: Task) -> None:
        """以新任务替换旧任务并保留其原队列位置（允许变更 task_id），单事务执行。

        旧任务及其关联的弹幕数据、失败记录将被一并删除，新任务按传入内容重新写入。

        Args:
            old_task_id (str): 被替换的旧任务标识。
            task (Task): 新任务数据。

        Raises:
            QueueStorageError: 旧任务不存在、目标字段不成对或数据库写入失败。
        """
        try:
            with queue_db.atomic():
                old = _QueueTask.get_or_none(_QueueTask.task_id == old_task_id)
                if old is None:
                    raise QueueStorageError(f"任务替换跳过：没有任务 [{old_task_id}] 的行")
                _QueueTask.delete().where(_QueueTask.task_id == old_task_id).execute()
                _QueueItem.delete().where(_QueueItem.task_id == old_task_id).execute()
                _QueueFailure.delete().where(_QueueFailure.task_id == old_task_id).execute()
                _QueueTask.insert(**self._row_values(task, old.position)).execute()
                self._insert_items(task.definition.task_id, task.definition.danmakus)
        except QueueStorageError:
            raise
        except Exception as e:
            logger.exception("任务替换失败 [task_id=%s]", old_task_id)
            raise QueueStorageError(f"任务替换失败 [{old_task_id}]", original_error=e) from e

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

        当 ``failure_reason`` 为 None 时，表示该条已发送成功或被跳过，若此前存在同索引的失败记录则一并删除；
        否则按 ``idx`` 写入或覆盖对应的失败原因。

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

    def load_all(self) -> list[Task]:
        """按队列顺序读取全部任务并组装为完整的任务对象（含弹幕列表）。

        注：``queue_failure`` 表数据暂未并入当前运行时模型。

        Returns:
            list[Task]: 按队列顺序排列的任务列表。

        Raises:
            QueueStorageError: 数据库读取或反序列化失败。
        """
        try:
            items_by_task: dict[str, list[Danmaku]] = {}
            for r in _QueueItem.select().order_by(_QueueItem.task_id, _QueueItem.idx):
                items_by_task.setdefault(r.task_id, []).append(
                    Danmaku(
                        msg=r.msg,
                        progress=r.progress,
                        mode=Danmaku.Mode(r.mode),
                        fontsize=r.fontsize,
                        color=r.color,
                    )
                )
            return [
                Task(
                    definition=TaskDefinition(
                        task_id=r.task_id,
                        target=VideoTarget(bvid=r.bvid, cid=r.cid),
                        meta=TaskMeta(
                            video_title=r.video_title,
                            part_page=r.part_page,
                            part_title=r.part_title,
                            part_duration_ms=r.duration_ms,
                            xml_path=Path(r.source_path) if r.source_path else None,
                        ),
                        danmakus=tuple(items_by_task.get(r.task_id, ())),
                        config=TaskConfig(
                            min_delay=r.min_delay,
                            max_delay=r.max_delay,
                            burst_enabled=bool(r.burst_enabled),
                            burst_size=r.burst_size,
                            rest_min=r.rest_min,
                            rest_max=r.rest_max,
                        ),
                    ),
                    execution=TaskExecution(
                        status=TaskStatus[r.status],
                        error_msg=r.error or "",
                        attempted=r.cursor,
                    ),
                )
                for r in _QueueTask.select().order_by(_QueueTask.position, _QueueTask.task_id)
            ]
        except Exception as e:
            logger.exception("队列读取失败")
            raise QueueStorageError("队列读取失败", original_error=e) from e

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

    def delete_tasks(self, task_ids: Sequence[str]) -> None:
        """批量删除指定任务及其关联数据，并重排剩余任务的顺序，单事务执行。

        Args:
            task_ids (Sequence[str]): 待删除的任务标识序列；不存在的标识将被忽略。

        Raises:
            QueueStorageError: 数据库删除或重排失败。
        """
        ids = list(task_ids)
        try:
            with queue_db.atomic():
                _QueueTask.delete().where(_QueueTask.task_id.in_(ids)).execute()
                _QueueItem.delete().where(_QueueItem.task_id.in_(ids)).execute()
                _QueueFailure.delete().where(_QueueFailure.task_id.in_(ids)).execute()
                remaining = list(_QueueTask.select().order_by(_QueueTask.position, _QueueTask.task_id))
                for position, r in enumerate(remaining):
                    if r.position != position:
                        _QueueTask.update(position=position).where(_QueueTask.task_id == r.task_id).execute()
        except Exception as e:
            logger.exception("队列任务删除失败")
            raise QueueStorageError("队列任务删除失败", original_error=e) from e

    def reset_tasks(self, task_ids: Sequence[str], *, status: TaskStatus, error: str | None) -> None:
        """将指定任务的发送进度、爆发计数与失败记录清零并更新状态，单事务执行。

        Args:
            task_ids (Sequence[str]): 待重置的任务标识序列。
            status (TaskStatus): 重置后的任务状态。
            error (str | None): 错误或中止说明；传入 None 以清空。

        Raises:
            QueueStorageError: 指定任务不存在，或数据库写入失败。
        """
        try:
            with queue_db.atomic():
                for task_id in task_ids:
                    updated = (
                        _QueueTask
                            .update(status=status.name, cursor=0, burst_count=0, error=error)
                            .where(_QueueTask.task_id == task_id)
                            .execute()
                    )
                    if updated == 0:
                        raise QueueStorageError(f"进度归零跳过：没有任务 [{task_id}] 的行")
                    _QueueFailure.delete().where(_QueueFailure.task_id == task_id).execute()
        except QueueStorageError:
            raise
        except Exception as e:
            logger.exception("队列进度归零失败")
            raise QueueStorageError("队列进度归零失败", original_error=e) from e

    def reset_queue(self, remove_ids: Sequence[str], revive_ids: Sequence[str]) -> None:
        """重置队列：删除 remove_ids 任务，revive_ids 清零进度并转待发，单事务执行。

        转待发的任务状态写 PENDING、错误清空、失败记录清空；两步要么都生效要么都不生效。

        Args:
            remove_ids (Sequence[str]): 待删除的任务标识序列。
            revive_ids (Sequence[str]): 待转待发的任务标识序列。

        Raises:
            QueueStorageError: 数据库写入失败。
        """
        try:
            with queue_db.atomic():
                self.delete_tasks(remove_ids)
                self.reset_tasks(revive_ids, status=TaskStatus.PENDING, error=None)
        except QueueStorageError:
            raise
        except Exception as e:
            logger.exception("队列重置失败")
            raise QueueStorageError("队列重置失败", original_error=e) from e

    def clear_all(self) -> None:
        """清空全部任务、弹幕与失败记录，单事务执行。

        Raises:
            QueueStorageError: 数据库写入失败。
        """
        try:
            with queue_db.atomic():
                _QueueTask.delete().execute()
                _QueueItem.delete().execute()
                _QueueFailure.delete().execute()
        except Exception as e:
            logger.exception("队列清空失败")
            raise QueueStorageError("队列清空失败", original_error=e) from e

    def close(self) -> None:
        """关闭数据库连接。"""
        if not queue_db.is_closed():
            queue_db.close()

    @staticmethod
    def _row_values(task: Task, position: int) -> dict:
        """将领域任务转换为 queue_task 表的列字典。

        注：``allow_duplicates`` 与 ``burst_count`` 尚未接入当前任务模型，暂按 0 写入。

        Args:
            task (Task): 待转换的领域任务对象。
            position (int): 队列中的 0-based 位置。

        Returns:
            dict: 对应数据库表列的键值映射。

        Raises:
            QueueStorageError: 目标字段不成对（bvid 与 cid 未同时存在或同时为空）。
        """
        definition = task.definition
        execution = task.execution
        meta = definition.meta
        if (definition.target.bvid is None) != (definition.target.cid is None):
            raise QueueStorageError("目标字段不成对：bvid 与 cid 必须成对有值或成对为空")
        return {
            "task_id": definition.task_id,
            "position": position,
            "bvid": definition.target.bvid,
            "cid": definition.target.cid,
            "video_title": meta.video_title,
            "part_page": meta.part_page,
            "part_title": meta.part_title,
            "duration_ms": meta.part_duration_ms,
            "source_path": str(meta.xml_path) if meta.xml_path else None,
            "min_delay": definition.config.min_delay,
            "max_delay": definition.config.max_delay,
            "burst_enabled": int(definition.config.burst_enabled),
            "burst_size": definition.config.burst_size,
            "rest_min": definition.config.rest_min,
            "rest_max": definition.config.rest_max,
            "allow_duplicates": 0,
            "status": execution.status.name,
            "cursor": execution.attempted,
            "burst_count": 0,
            "error": execution.error_msg or None,
        }

    @staticmethod
    def _next_position() -> int:
        """返回下一个可追加的队列位置（空队列时返回 0）。

        Returns:
            int: 末尾位置序号。
        """
        current = _QueueTask.select(fn.MAX(_QueueTask.position)).scalar()
        return 0 if current is None else current + 1

    @staticmethod
    def _insert_items(task_id: str, items: Sequence[Danmaku]) -> None:
        """分批写入弹幕数据，避免单次 SQLite 参数数量超出绑定上限。

        Args:
            task_id (str): 归属的任务唯一标识。
            items (Sequence[Danmaku]): 待插入的弹幕序列。
        """
        for start in range(0, len(items), _INSERT_BATCH):
            chunk = items[start:start + _INSERT_BATCH]
            _QueueItem.insert_many(
                [
                    {
                        "task_id": task_id,
                        "idx": start + offset,
                        "msg": dm.msg,
                        "progress": dm.progress,
                        "mode": int(dm.mode),
                        "fontsize": dm.fontsize,
                        "color": dm.color,
                    }
                    for offset, dm in enumerate(chunk)
                ]
            ).execute()
