from pathlib import Path

from platformdirs import user_data_dir

from danmaku_sender._version import __version__


# 应用数据目录（import 时计算，运行时不变）
_DATA_DIR = Path(user_data_dir("BiliDanmakuSender", "Miku_oso"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)


class AppInfo:
    """存放应用元数据"""
    NAME = "B站弹幕发射器"
    NAME_EN = "BiliDanmakuSender"
    AUTHOR = "Miku_oso"
    VERSION = __version__
    LOG_FILE_NAME = "latest.log"

    class Paths:
        """所有应用路径的集中定义"""
        DATA = _DATA_DIR
        HISTORY_DB = _DATA_DIR / "history.db"
        CONFIG = _DATA_DIR / "config.json"
        LOGS = _DATA_DIR / "logs"
        ACCOUNTS = _DATA_DIR / "accounts.json"


class UI:
    """存放所有UI相关的静态配置"""
    MAIN_WINDOW_TITLE = f"{AppInfo.NAME} v{AppInfo.VERSION}"
    HELP_WINDOW_TITLE = "使用说明"
    CHECK_UPDATE_MENU_LABEL = "检查新版本"
    ABOUT_WINDOW_SHORT_TITLE = "关于"
    ABOUT_WINDOW_TITLE = f"关于 {AppInfo.NAME}"


class Links:
    """存放所有外部URL"""
    GITHUB_REPO = "https://github.com/TouhouGleaners/danmaku-sender"
    GITHUB_ISSUES = f"{GITHUB_REPO}/issues"
    GITHUB_API_RELEASES = "https://api.github.com/repos/TouhouGleaners/danmaku-sender/releases"