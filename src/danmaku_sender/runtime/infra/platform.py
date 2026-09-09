"""平台相关服务 - 系统级功能（通知、电源管理等）"""

import ctypes
import logging
import platform
import threading

from danmaku_sender.config.app_meta import AppInfo


logger = logging.getLogger(__name__)


IS_WINDOWS = platform.system() == "Windows"


# region Windows Toast 通知

ICON_PATH = AppInfo.Paths.ASSETS / 'icon.ico'

if not ICON_PATH.is_file():
    logger.warning(f"图标文件未找到: {ICON_PATH}。通知将可能没有图标。")
    ICON_PATH = ""
else:
    ICON_PATH = str(ICON_PATH)

try:
    from win11toast import toast
except ImportError:
    toast = None
    logger.warning("未能导入 'win11toast' 库。桌面通知功能将被禁用。")


def _send_notification_wrapper(title: str, message: str):
    """内部包装函数，用于在独立的线程中安全地调用 toast 并处理异常。"""
    try:
        if callable(toast):
            toast(title=title, body=message, icon=ICON_PATH, app_id=AppInfo.NAME)
        logger.info(f"成功发送通知: {title}")
    except Exception as e:
        logger.error(f"发送通知 {title} 时发生未知错误: {e}。", exc_info=True)


def send_windows_notification(title: str, message: str):
    """在后台启动一个线程来发送 Windows 桌面通知。"""
    if toast is None or not IS_WINDOWS:
        logger.debug(f"跳过通知 (依赖缺失或非Windows系统): {title}")
        return

    notification_thread = threading.Thread(
        target=_send_notification_wrapper,
        args=(title, message),
        name="Notification",
        daemon=True
    )
    notification_thread.start()


# endregion


# region 电源管理

class PowerManagement:
    """系统电源管理工具类 (仅限 Windows)"""
    # Windows API 常量
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002

    # 类级锁和计数器
    _sleep_lock = threading.Lock()
    _prevent_sleep_count = 0

    @staticmethod
    def prevent_sleep():
        """申请阻止系统休眠。

        增加引用计数；仅当计数从 0 变为 1 时，调用系统 API。
        """
        if not IS_WINDOWS:
            return

        with PowerManagement._sleep_lock:
            PowerManagement._prevent_sleep_count += 1
            current_count = PowerManagement._prevent_sleep_count

            if current_count > 1:
                logger.debug(f"已增加阻止系统休眠引用计数，当前: {current_count}")
                return

        # 仅在计数为 1 时真正调用 API
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(
                PowerManagement.ES_CONTINUOUS | PowerManagement.ES_SYSTEM_REQUIRED
            )
            logger.info("已启用[阻止系统休眠]模式。")
        except Exception as e:
            logger.error(f"无法设置阻止休眠状态: {e}")

    @staticmethod
    def allow_sleep():
        """释放阻止休眠申请。

        减少引用计数；仅当计数降为 0 时，调用系统 API 恢复默认策略。
        """
        if not IS_WINDOWS:
            return

        should_reset = False

        with PowerManagement._sleep_lock:
            if PowerManagement._prevent_sleep_count == 0:
                logger.warning("尝试释放休眠阻止，但计数已为 0。")
                return

            PowerManagement._prevent_sleep_count -= 1
            current_count = PowerManagement._prevent_sleep_count

            if current_count > 0:
                logger.debug(f"已减少阻止系统休眠引用计数，剩余: {current_count}")
                return

            should_reset = True

        if should_reset:
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(
                    PowerManagement.ES_CONTINUOUS
                )
                logger.info("引用计数归零，已恢复系统正常休眠策略。")
            except Exception as e:
                logger.error(f"无法恢复休眠策略: {e}")


class KeepSystemAwake:
    """上下文管理器：在代码块执行期间阻止系统休眠 (仅限 Windows)"""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def __enter__(self):
        if self.enabled:
            PowerManagement.prevent_sleep()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.enabled:
            PowerManagement.allow_sleep()


# endregion
