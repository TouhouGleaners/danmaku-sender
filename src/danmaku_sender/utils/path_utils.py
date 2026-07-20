"""路径工具函数"""

from pathlib import Path


def find_assets_dir(anchor_file: str) -> Path:
    """从指定文件向上遍历查找 assets 目录，兼容开发环境和 Nuitka 打包。

    Args:
        anchor_file: 起始文件的 __file__ 值，通常传 __file__ 即可。

    Returns:
        找到的 assets 目录路径。
    """
    current_path = Path(anchor_file).resolve().parent

    for _ in range(5):
        candidate = current_path / "assets"
        if candidate.is_dir():
            return candidate

        if current_path.parent == current_path:
            break
        current_path = current_path.parent

    return Path(anchor_file).resolve().parents[3] / "assets"
