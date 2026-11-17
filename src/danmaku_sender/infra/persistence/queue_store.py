"""队列落盘：queue.db 的行存取，队列事实源的地基。

行契约按任务抽屉分列：

- **冷列**（入队 / 编辑时写一次）：``destination_json``（选定的分P，未指定为 None）、``pack_json``（弹幕包）、``options_json``（发送策略）；
- **热列**（逐条结算即写）：``status``、``cursor``、``burst_count``、``failed_json``、``error``；
- ``position`` 管队列顺序。

两类写入互不相扰：进度落账只碰热列，改配置只碰冷列。
本模块只认行、不认任务模型——任务值与行的映射归接线层。
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from peewee import (
    CharField,
    DatabaseProxy,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
)

from danmaku_sender.types.exceptions.exceptions import QueueStorageError

logger = logging.getLogger(__name__)

queue_db = DatabaseProxy()


class _QueueRow(Model):
    """queue.db 的行表（模块内部）。"""

    task_id = CharField(primary_key=True)
    position = IntegerField()
    destination_json = TextField(null=True)
    pack_json = TextField()
    options_json = TextField()
    status = CharField()
    cursor = IntegerField(default=0)
    burst_count = IntegerField(default=0)
    failed_json = TextField(default="[]")
    error = TextField(null=True)

    class Meta:
        table_name = "queue_row"
        database = queue_db


@dataclass(frozen=True)
class QueueRow:
    """queue.db 的一行：任务数据的落盘形态。

    Attributes:
        task_id (str): 任务标识。
        position (int): 队列顺序，小者在前。
        destination_json (str | None): 选定分P的 JSON；None = 未指定目标。
        pack_json (str): 弹幕包的 JSON。
        options_json (str): 发送策略的 JSON。
        status (str): 状态名（取枚举的 name）。
        cursor (int): 续传游标，下一条待处理的弹幕下标。
        burst_count (int): 爆发相位计数。
        failed_json (str): 失败条目的 JSON 数组。
        error (str | None): 失败或中止原因；None 表示没有错误。
    """
    task_id: str
    position: int
    destination_json: str | None
    pack_json: str
    options_json: str
    status: str
    cursor: int = 0
    burst_count: int = 0
    failed_json: str = "[]"
    error: str | None = None


class QueueStore:
    """queue.db 的行存取入口。

    写入失败抛 :class:`QueueStorageError`，不吞错、不假装成功。
    """

    def __init__(self, db_path: Path) -> None:
        """打开（或创建）队列库并确保行表存在。

        Args:
            db_path: queue.db 的路径。
        """
        self.db_path = db_path
        queue_db.initialize(SqliteDatabase(str(db_path)))
        queue_db.connect(reuse_if_open=True)
        queue_db.create_tables([_QueueRow], safe=True)

    def save(self, row: QueueRow) -> None:
        """整行写入（入队 / 编辑 / 调序）：同 task_id 覆盖。

        Args:
            row (QueueRow): 待写入的行。

        Raises:
            QueueStorageError: 写入失败。
        """
        try:
            (
                _QueueRow
                .insert(
                    task_id=row.task_id,
                    position=row.position,
                    destination_json=row.destination_json,
                    pack_json=row.pack_json,
                    options_json=row.options_json,
                    status=row.status,
                    cursor=row.cursor,
                    burst_count=row.burst_count,
                    failed_json=row.failed_json,
                    error=row.error,
                )
                .on_conflict(
                    conflict_target=[_QueueRow.task_id],
                    update={
                        _QueueRow.position: row.position,
                        _QueueRow.destination_json: row.destination_json,
                        _QueueRow.pack_json: row.pack_json,
                        _QueueRow.options_json: row.options_json,
                        _QueueRow.status: row.status,
                        _QueueRow.cursor: row.cursor,
                        _QueueRow.burst_count: row.burst_count,
                        _QueueRow.failed_json: row.failed_json,
                        _QueueRow.error: row.error,
                    },
                )
                .execute()
            )
        except Exception as e:
            logger.exception("队列行写入失败 [task_id=%s]", row.task_id)
            raise QueueStorageError(f"队列行写入失败 [{row.task_id}]", original_error=e) from e

    def update_state(
        self,
        task_id: str,
        *,
        status: str,
        cursor: int,
        burst_count: int = 0,
        failed_json: str = "[]",
        error: str | None = None,
    ) -> None:
        """只写热列（逐条结算 / 状态变更用），冷列原样不动。

        Args:
            task_id (str): 任务标识。
            status (str): 状态名。
            cursor (int): 续传游标。
            burst_count (int): 爆发相位计数。
            failed_json (str): 失败条目的 JSON 数组。
            error (str | None): 失败或中止原因。

        Raises:
            QueueStorageError: 写入失败。
        """
        try:
            updated = (
                _QueueRow
                .update(
                    status=status,
                    cursor=cursor,
                    burst_count=burst_count,
                    failed_json=failed_json,
                    error=error,
                )
                .where(_QueueRow.task_id == task_id)
                .execute()
            )
            if updated == 0:
                raise QueueStorageError(f"热列写入跳过：没有任务 [{task_id}] 的行")
        except QueueStorageError:
            raise
        except Exception as e:
            logger.exception("队列热列写入失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"队列热列写入失败 [{task_id}]", original_error=e) from e

    def load_rows(self) -> list[QueueRow]:
        """按队列顺序读出全部行。

        Returns:
            list[QueueRow]: position 升序的行列表。

        Raises:
            QueueStorageError: 读取失败。
        """
        try:
            rows = _QueueRow.select().order_by(_QueueRow.position, _QueueRow.task_id)
            return [
                QueueRow(
                    task_id=r.task_id,
                    position=r.position,
                    destination_json=r.destination_json,
                    pack_json=r.pack_json,
                    options_json=r.options_json,
                    status=r.status,
                    cursor=r.cursor,
                    burst_count=r.burst_count,
                    failed_json=r.failed_json,
                    error=r.error,
                )
                for r in rows
            ]
        except Exception as e:
            logger.exception("队列行读取失败")
            raise QueueStorageError("队列行读取失败", original_error=e) from e

    def delete(self, task_id: str) -> None:
        """删除一行（移除任务用）；不存在时静默返回。

        Args:
            task_id (str): 任务标识。

        Raises:
            QueueStorageError: 删除失败。
        """
        try:
            _QueueRow.delete().where(_QueueRow.task_id == task_id).execute()
        except Exception as e:
            logger.exception("队列行删除失败 [task_id=%s]", task_id)
            raise QueueStorageError(f"队列行删除失败 [{task_id}]", original_error=e) from e

    def close(self) -> None:
        """关闭数据库连接。"""
        if not queue_db.is_closed():
            queue_db.close()
