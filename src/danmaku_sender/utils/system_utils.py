import ctypes
import logging
import platform
import threading


logger = logging.getLogger("SystemUtils")

IS_WINDOWS = platform.system() == "Windows"

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
        """
        申请阻止系统休眠。
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
        """
        释放阻止休眠申请。
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