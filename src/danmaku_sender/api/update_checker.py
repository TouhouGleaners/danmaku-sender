import logging
import requests
from packaging import version

from ..config.app_config import Links


logger = logging.getLogger("UpdateChecker")


class UpdateInfo:
    """更新信息数据类"""
    def __init__(self, has_update: bool, remote_version: str = "", release_notes: str = "", url: str = ""):
        self.has_update = has_update
        self.remote_version = remote_version
        self.release_notes = release_notes
        self.url = url


class UpdateChecker:
    @staticmethod
    def check(current_version: str, use_system_proxy: bool) -> UpdateInfo:
        """检查是否有新版本发布"""
        session = requests.Session()
        if not use_system_proxy:
            session.trust_env = False
            session.proxies = {"http": None, "https": None}

        api_url = f"{Links.GITHUB_API_RELEASES}?per_page=1"
        logger.info("正在连接 GitHub 检查更新...")

        response = session.get(api_url, timeout=10)
        response.raise_for_status()

        data_list = response.json()
        if not data_list or not isinstance(data_list, list):
            logger.warning("未找到任何发布信息")
            return UpdateInfo(False)
        
        data = data_list[0]
        remote_tag = data.get("tag_name", "").lstrip("v")
        release_notes = data.get("body") or "暂无更新日志"
        release_url = data.get("html_url", Links.GITHUB_REPO)

        try:
            local_ver = version.parse(current_version)
            remote_ver = version.parse(remote_tag)
        except Exception as e:
            logger.warning(f"版本号解析失败: {e}")
            return UpdateInfo(False)

        if remote_ver > local_ver:
            logger.info(f"发现新版本: v{remote_tag}")
            return UpdateInfo(True, remote_tag, release_notes, release_url)
        else:
            logger.info(f"当前已是最新版本 ({local_ver})")
            return UpdateInfo(False)