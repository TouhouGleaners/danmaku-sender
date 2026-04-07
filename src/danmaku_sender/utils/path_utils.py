from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


def get_assets_path() -> Path:
    """获取 assets 文件夹路径"""
    current_path = Path(__file__).resolve().parent
    for _ in range(5):
        candidate = current_path / 'assets'
        if candidate.exists() and candidate.is_dir():
            return candidate

        if current_path.parent == current_path:
            break
        current_path = current_path.parent

    return Path(__file__).resolve().parents[3] / 'assets'