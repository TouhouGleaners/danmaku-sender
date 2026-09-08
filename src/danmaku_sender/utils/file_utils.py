"""文件操作工具函数"""

import json
import os
import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


@contextmanager
def atomic_write(
    path: Path,
    mode: str = 'w',
    encoding: str = 'utf-8',
    errors: str = 'strict',
):
    """原子写入上下文管理器：先写临时文件，退出时强制落盘并原子替换。

    保证崩溃一致性（Crash-safe）。即使在写入过程中断电或进程强杀，
    也不会损坏原目标文件。

    使用方式:
        写文本（默认）
        with atomic_write(path) as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        写二进制
        with atomic_write(path, mode='wb') as f:
            f.write(data)

    Args:
        path: 目标文件路径
        mode: 文件打开模式，默认 'w'（文本写入），'wb' 为二进制写入
        encoding: 文本模式下的字符编码，默认 utf-8
        errors: 编码错误处理策略 ('strict', 'replace', 'ignore' 等)
    """
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp"
    )
    tmp_path = Path(tmp_path)
    is_binary = 'b' in mode
    success = False

    try:
        with os.fdopen(
            fd,
            mode=mode,
            encoding=None if is_binary else encoding,
            errors=None if is_binary else errors
        ) as f:
            yield f
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, target)
        success = True

    finally:
        if not success:
            tmp_path.unlink(missing_ok=True)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """原子写入二进制数据。

    Args:
        path: 目标文件路径
        data: 要写入的二进制数据
    """
    with atomic_write(path, mode='wb') as f:
        f.write(data)


def atomic_write_text(
    path: Path,
    text: str,
    encoding: str = 'utf-8',
) -> None:
    """原子写入文本数据。

    Args:
        path: 目标文件路径
        text: 要写入的文本字符串
        encoding: 字符编码，默认 utf-8
    """
    with atomic_write(path, mode='w', encoding=encoding) as f:
        f.write(text)


def read_text(path: Path, default: str = "", encoding: str = "utf-8") -> str:
    """读取文本文件，若文件不存在则返回默认值。

    Args:
        path: 文件路径
        default: 文件不存在时返回的默认值
        encoding: 字符编码

    Returns:
        文件内容或默认值
    """
    if not path.is_file():
        return default
    try:
        return path.read_text(encoding=encoding)
    except OSError as e:
        logger.warning(f"读取文件失败 [{path}]: {e}")
        return default


def read_json[T](
    path: Path,
    default: T = None,
    backup_if_corrupt: bool = False,
    encoding: str = "utf-8"
) -> Any | T:
    """安全读取并解析 JSON 文件。

    - 文件不存在：静默返回 default（不记录 error 日志，视为首次启动默认状态）；
    - JSON 格式损坏：记录 error 日志，可选备份损坏文件为 .corrupt，并返回 default；
    - 权限等系统 I/O 错误：记录 error 日志，返回 default。

    Args:
        path: JSON 文件路径
        default: 失败或文件不存在时返回的默认值
        backup_if_corrupt: 若文件损坏是否自动备份为 .corrupt
        encoding: 字符编码
    """
    if not path.is_file():
        return default

    try:
        content = path.read_text(encoding=encoding)
        if not content.strip():
            return default
        return json.loads(content)

    except json.JSONDecodeError as e:
        logger.error(f"JSON 配置文件损坏 [{path}]: {e}")
        if backup_if_corrupt:
            backup_corrupt_file(path)
        return default

    except (OSError, UnicodeError) as e:
        logger.error(f"读取文件失败 [{path}]: {e}")
        return default


def backup_corrupt_file(path: Path, suffix: str = ".corrupt") -> Path | None:
    """将损坏的文件备份为追加后缀。

    Args:
        path: 文件路径
        suffix: 备份文件后缀（追加到原文件名后）

    Returns:
        备份文件路径，如果备份失败返回 None

    Example:
        accounts.json → accounts.json.corrupt
    """
    if not path.exists():
        return None

    dst = path.with_name(f"{path.name}{suffix}")
    try:
        path.rename(dst)
        logger.info(f"已将损坏的文件备份为: {dst}")
        return dst
    except OSError as e:
        logger.error(f"无法备份损坏的文件: {e}")
        return None
