import logging
import requests
import webbrowser
import threading
from packaging import version
from tkinter import messagebox

from ..config.app_config import AppInfo, Links


logger = logging.getLogger("UpdateChecker")

class UpdateChecker:
    @staticmethod
    def check_for_updates(app_window, use_system_proxy: bool, quiet: bool = True):
        """
        检查是否有新版本发布。
        如果有新版本，弹出对话框提示用户更新。
        """
        thread = threading.Thread(
            target=UpdateChecker._worker,
            args=(app_window, use_system_proxy, quiet),
            daemon=True
        )
        thread.start()

    @staticmethod
    def _worker(app_window, use_system_proxy: bool, quiet: bool):
        try:
            logger.info("正在连接 GitHub 检查更新...")

            session = requests.Session()
            if not use_system_proxy:
                session.trust_env = False
                session.proxies = {"http": None, "https": None}

            api_url = Links.GITHUB_API_LATEST
            response = session.get(f"{api_url}?per_page=1", timeout=10)

            if response.status_code != 200:
                logger.warning(f"检查更新失败: HTTP {response.status_code}")
                if not quiet:
                    app_window.after(0, lambda: messagebox.showerror(
                        "检查失败", 
                        f"连接 GitHub 失败 (HTTP {response.status_code})。\n请检查网络连接或代理设置。", 
                        parent=app_window
                    ))
                return
            data_list = response.json()
            if not data_list:
                logger.info("未找到任何发布版本信息。")
                return

            data = data_list[0]

            remote_tag = data.get("tag_name", "").lstrip("v")
            release_notes = data.get("body", "暂无更新日志")
            release_url = data.get("html_url", Links.GITHUB_REPO)

            local_ver = version.parse(AppInfo.VERSION)
            remote_ver = version.parse(remote_tag)

            if remote_ver > local_ver:
                logger.info(f"发现新版本: {remote_tag}")
                app_window.after(0, lambda: UpdateChecker._show_update_dialog(
                    app_window, remote_tag, release_notes, release_url
                ))
            else:
                logger.info(f"当前已是最新版本 ({local_ver})")
                if not quiet:
                    app_window.after(0, lambda: messagebox.showinfo(
                        "检查更新", f"当前版本 v{AppInfo.VERSION} 已是最新。", parent=app_window
                    ))

        except requests.RequestException as e:
            logger.warning(f"检查更新网络错误: {e}")
            if not quiet:
                # 只有手动检查时，才给用户详细的“教育性”提示
                app_window.after(0, lambda: messagebox.showerror(
                    "网络连接失败", 
                    "无法连接到 GitHub 服务器。\n\n"
                    "建议尝试以下操作：\n"
                    "1. 开启 VPN 或系统代理。\n"
                    "2. 确保设置页勾选了“使用系统代理”。", 
                    parent=app_window
                ))
        except Exception as e:
            logger.error(f"检查更新内部错误: {e}", exc_info=True)
            if not quiet:
                app_window.after(0, lambda: messagebox.showerror(
                    "错误", f"发生未知错误: {e}", parent=app_window
                ))

    @staticmethod
    def _show_update_dialog(parent, ver, notes, url):
        """显示更新弹窗"""
        if len(notes) > 800:
            notes = notes[:800] + "\n... (更多内容请查看网页)"
            
        ask = messagebox.askyesno(
            title="发现新版本",
            message=f"发现新版本: v{ver}\n\n"
                    f"--- 更新内容 ---\n{notes}\n\n"
                    "是否前往 GitHub 发布页面下载？",
            parent=parent
        )
        if ask:
            webbrowser.open(url)