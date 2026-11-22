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
from collections.abc import Iterator, Sequence
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


class _QueueMapper:
    """领域任务与数据表之间的双向映射，不执行任何数据库操作。"""

    @staticmethod
    def to_row_values(task: Task, position: int) -> dict:
        """将领域任务转换为 queue_task 表的列字典。

        注：``allow_duplicates`` 与 ``burst_count`` 尚未接入当前任务模型，暂默认写入 0。

        Args:
            task (Task): 待转换的领域任务对象。
            position (int): 队列中的 0-based 索引。

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
    def to_item_batches(task_id: str, items: Sequence[Danmaku]) -> Iterator[list[dict]]:
        """将弹幕序列按批次切分为 queue_item 表的行字典列表。

        每批不超过 ``_INSERT_BATCH`` 行，避免单次 SQLite 参数数量超出绑定上限。

        Args:
            task_id (str): 归属的任务唯一标识。
            items (Sequence[Danmaku]): 待写入的弹幕序列。

        Yields:
            list[dict]: 单批弹幕行字典列表。
        """
        for start in range(0, len(items), _INSERT_BATCH):
            chunk = items[start:start + _INSERT_BATCH]
            yield [
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

    @staticmethod
    def to_danmaku(row: _QueueItem) -> Danmaku:
        """将弹幕行记录转换为单条弹幕对象。

        Args:
            row (_QueueItem): queue_item 表行记录。

        Returns:
            Danmaku: 转换后的弹幕对象。
        """
        return Danmaku(
            msg=row.msg,
            progress=row.progress,
            mode=Danmaku.Mode(row.mode),
            fontsize=row.fontsize,
            color=row.color,
        )

    @staticmethod
    def to_task(row: _QueueTask, danmakus: Sequence[Danmaku]) -> Task:
        """将任务行记录与弹幕序列组装为领域任务对象。

        Args:
            row (_QueueTask): queue_task 表行记录。
            danmakus (Sequence[Danmaku]): 关联的弹幕序列，按原始索引升序排列。

        Returns:
            Task: 组装完成的领域任务对象。
        """
        return Task(
            definition=TaskDefinition(
                task_id=row.task_id,
                target=VideoTarget(bvid=row.bvid, cid=row.cid),
                meta=TaskMeta(
                    video_title=row.video_title,
                    part_page=row.part_page,
                    part_title=row.part_title,
                    part_duration_ms=row.duration_ms,
                    xml_path=Path(row.source_path) if row.source_path else None,
                ),
                danmakus=tuple(danmakus),
                config=TaskConfig(
                    min_delay=row.min_delay,
                    max_delay=row.max_delay,
                    burst_enabled=bool(row.burst_enabled),
                    burst_size=row.burst_size,
                    rest_min=row.rest_min,
                    rest_max=row.rest_max,
                ),
            ),
            execution=TaskExecution(
                status=TaskStatus[row.status],
                error_msg=row.error or "",
                attempted=row.cursor,
            ),
        )


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
    def open(cls, db_path: Path) -> "QueueStore":
        """打开队列数据库并执行一次全量读取校验。

        若数据库文件损坏或无法读取，先关闭连接并将主库及 WAL 附属文件备份，随后创建空库重新打开；
        若重建后仍无法打开，则向上抛出异常。
        若存在异常退出残留的 RUNNING 任务，则重置为 PAUSED（见 :meth:`_QueueRecovery.pause_stale_running`）。

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
            loaded = store.load_all()
        except QueueStorageError:
            if store is not None:
                store.close()
            if not _QueueRecovery.is_corrupt(db_path):
                raise
            logger.exception("队列库已损坏，备份后以空库启动 [%s]", db_path)
            _QueueRecovery.backup_corrupt(db_path)
            return cls(db_path)

        if any(t.status is TaskStatus.RUNNING for t in loaded):
            _QueueRecovery.pause_stale_running()
        return store

    def add_task(self, task: Task) -> None:
        """将新任务追加至队列末尾，连同弹幕数据一并写入，单事务执行。

        Args:
            task (Task): 待入队的任务。

        Raises:
            QueueStorageError: 目标字段不成对或数据库写入失败。
        """
        try:
            with queue_db.atomic():
                current = _QueueTask.select(fn.MAX(_QueueTask.position)).scalar()
                at = 0 if current is None else current + 1
                _QueueTask.insert(**_QueueMapper.to_row_values(task, at)).execute()
                for batch in _QueueMapper.to_item_batches(task.definition.task_id, task.definition.danmakus):
                    _QueueItem.insert_many(batch).execute()
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
                _QueueTask.insert(**_QueueMapper.to_row_values(task, at)).execute()
                for batch in _QueueMapper.to_item_batches(task.definition.task_id, task.definition.danmakus):
                    _QueueItem.insert_many(batch).execute()
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
                _QueueTask.update(**_QueueMapper.to_row_values(task, old.position)).where(_QueueTask.task_id == task_id).execute()
                if items_replaced:
                    _QueueItem.delete().where(_QueueItem.task_id == task_id).execute()
                    _QueueFailure.delete().where(_QueueFailure.task_id == task_id).execute()
                    for batch in _QueueMapper.to_item_batches(task_id, task.definition.danmakus):
                        _QueueItem.insert_many(batch).execute()
        except QueueStorageError:
            raise
        except Exception as e:
            logger.exception("队列任务更新失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"队列任务更新失败 [{task_id}]", original_error=e) from e

    def replace_task(self, old_task_id: str, task: Task) -> None:
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
                _QueueTask.insert(**_QueueMapper.to_row_values(task, old.position)).execute()
                for batch in _QueueMapper.to_item_batches(task.definition.task_id, task.definition.danmakus):
                    _QueueItem.insert_many(batch).execute()
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
                items_by_task.setdefault(r.task_id, []).append(_QueueMapper.to_danmaku(r))
            return [
                _QueueMapper.to_task(r, items_by_task.get(r.task_id, ()))
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


class _QueueRecovery:
    """queue.db 的启动恢复协调器

    负责损坏判定、备份隔离与残留运行态恢复。
    """

    @staticmethod
    def is_corrupt(db_path: Path) -> bool:
        """判断库文件是否已失去 SQLite 文件格式（如被截断或覆盖写坏）。

        若文件头仍为有效的 SQLite 格式，读取失败更可能源于临时锁定或 I/O 故障，此时保留原文件并向上抛出异常，不按损坏处理。

        Args:
            db_path (Path): queue.db 的文件路径。

        Returns:
            bool: 文件存在且文件头非 SQLite 格式时返回 True。
        """
        try:
            with open(db_path, "rb") as fh:
                return fh.read(16) != b"SQLite format 3\x00"
        except OSError:
            return False

    @staticmethod
    def backup_corrupt(db_path: Path) -> None:
        """备份损坏的数据库文件及其 WAL / SHM 附属文件。

        备份后缀附加精确时间戳，避免重复损坏时与既有备份冲突，同时防止重建同路径数据库时重放遗留的 WAL 日志。

        Args:
            db_path (Path): queue.db 的文件路径。

        Raises:
            QueueStorageError: 任一待备份文件重命名失败，无法安全重建数据库。
        """
        stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns()}"
        for suffix in ("", "-wal", "-shm"):
            path = db_path.parent / f"{db_path.name}{suffix}"
            if path.exists() and backup_corrupt_file(path, suffix=f".corrupt-{stamp}") is None:
                raise QueueStorageError(f"无法备份损坏的队列库 [{path}]")

    @staticmethod
    def pause_stale_running() -> None:
        """将异常退出残留的 RUNNING 任务重置为 PAUSED，并清零过期爆发计数。

        续传游标保持不变，以便任务从上次记录的进度位置继续发送。
        写入失败仅记录日志、不阻断启动，避免将暂时锁定的正常数据库误判为损坏。
        """
        try:
            (_QueueTask
                .update(status=TaskStatus.PAUSED.name, burst_count=0)
                .where(_QueueTask.status == TaskStatus.RUNNING.name)
                .execute()
            )
        except Exception:
            logger.exception("启动自愈写入失败")
