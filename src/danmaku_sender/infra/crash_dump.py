"""崩溃转储文件的启动轮转。

启动时留存上一份非空转储、清理超出上限的旧件，并创建本次运行的转储文件。
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

logger = logging.getLogger(__name__)


class CrashDumpLog:
    """崩溃转储文件的启动轮转与总量控制。

    Attributes:
        keep (int): 留存的历史转储份数。
    """

    FILE_NAME = "faulthandler.log"
    ARCHIVE_PREFIX = "faulthandler-"
    ARCHIVE_SUFFIX = ".log"

    # 进程级资源：句柄须活到解释器结束，否则转储会在启动失败、
    # 退出时仍有线程运行、解释器关闭三个窗口里落到已关闭的句柄
    _handle: IO[str] | None = None

    def __init__(self, keep: int = 5) -> None:
        """建立轮转器。

        Args:
            keep (int): 留存的历史转储份数，超出的最旧者被删除。
        """
        self.keep = keep

    def prepare(self, log_dir: Path) -> IO[str] | None:
        """留存上一份转储并返回本次的写入句柄。

        Args:
            log_dir (Path): 转储所在目录。

        Returns:
            IO[str] | None: 本次的写入句柄；无法取得时为 ``None``。
        """
        current = log_dir / self.FILE_NAME
        try:
            self._archive(current)
            self._prune(log_dir)
            type(self)._handle = open(current, "w", encoding="utf-8")
            return type(self)._handle
        except OSError as e:
            logger.warning(f"崩溃转储不可用，已跳过诊断: {e}")
            return None

    def _archive(self, current: Path) -> None:
        """将上一份非空转储重命名为按日期归组的归档。

        同日多次崩溃依次取 ``faulthandler-YYYYMMDD.log``、``-1``、``-2``……

        Args:
            current (Path): 本次运行使用的转储路径。
        """
        if not current.exists() or current.stat().st_size == 0:
            return

        # 归档名取本地日期，先按 UTC 取时刻再转本地时区
        day = (
            datetime
                .fromtimestamp(current.stat().st_mtime, tz=timezone.utc)
                .astimezone()
                .strftime("%Y%m%d")
        )
        target = current.with_name(f"{self.ARCHIVE_PREFIX}{day}{self.ARCHIVE_SUFFIX}")
        counter = 1
        while target.exists():
            target = current.with_name(f"{self.ARCHIVE_PREFIX}{day}-{counter}{self.ARCHIVE_SUFFIX}")
            counter += 1
        current.replace(target)

    def _prune(self, log_dir: Path) -> None:
        """按留存上限删除最旧的归档。

        Args:
            log_dir (Path): 转储所在目录。
        """
        pattern = f"{self.ARCHIVE_PREFIX}*{self.ARCHIVE_SUFFIX}"
        archives = sorted(log_dir.glob(pattern), key=lambda p: p.stat().st_mtime_ns)
        for stale in archives[: max(0, len(archives) - self.keep)]:
            stale.unlink(missing_ok=True)
