"""文件操作工具函数"""

import os
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """原子写入二进制数据：先写临时文件，再原子替换。

    即使在写入过程中崩溃，也不会损坏原文件。

    Args:
        path: 目标文件路径
        data: 要写入的二进制数据
    """
    tmp_path = path.with_suffix('.tmp')

    try:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, path)  # 原子操作

    except Exception:
        # 清理临时文件
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def atomic_write_text(path: Path, text: str, encoding: str = 'utf-8') -> None:
    """原子写入文本数据：先写临时文件，再原子替换。

    即使在写入过程中崩溃，也不会损坏原文件。

    Args:
        path: 目标文件路径
        text: 要写入的文本
        encoding: 编码格式
    """
    tmp_path = path.with_suffix('.tmp')

    try:
        tmp_path.write_text(text, encoding=encoding)
        os.replace(tmp_path, path)  # 原子操作

    except Exception:
        # 清理临时文件
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise
