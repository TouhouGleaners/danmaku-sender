import ctypes
import logging
import platform


logger = logging.getLogger("SystemUtils")

class PowerManagement:
    """系统电源管理工具类 (仅限 Windows)"""
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002

    @staticmethod
    def prevent_sleep():
        """阻止系统休眠，但允许屏幕关闭"""
        if platform.system() != "Windows": return
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(
                PowerManagement.ES_CONTINUOUS | PowerManagement.ES_SYSTEM_REQUIRED
            )
            logger.info("已启用[阻止系统休眠]模式。")
        except Exception as e:
            logger.error(f"无法设置阻止休眠状态: {e}")

    @staticmethod
    def allow_sleep():
        """恢复系统正常休眠策略"""
        if platform.system() != "Windows": return
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(
                PowerManagement.ES_CONTINUOUS
            )
            logger.info("已恢复系统正常休眠策略。")
        except Exception as e:
            logger.error(f"无法恢复休眠策略: {e}")