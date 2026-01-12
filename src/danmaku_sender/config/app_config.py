class AppInfo:
    """存放应用元数据"""
    NAME = "B站弹幕补档工具"
    NAME_EN = "BiliDanmakuSender"
    AUTHOR = "Miku_oso"
    VERSION = "2.0.0"
    LOG_FILE_NAME = "latest.log"
    LOG_DIR_NAME = "logs"
    

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