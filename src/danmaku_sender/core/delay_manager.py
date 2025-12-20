import time
import random
import logging
from threading import Event

class DelayManager:
    """
    延迟管理器
    支持：
    1. 基础随机延迟 (normal_min ~ normal_max)
    2. 爆发模式 (Burst Mode): 每发送 N 条后，进行一次长休息
    """
    def __init__(self,
                 normal_min: float,
                 normal_max: float,
                 burst_size: int = 0,
                 rest_min: float = 0,
                 rest_max: float = 0):
        """

        Args:
            normal_min (float): 普通最小间隔时间（秒）
            normal_max (float): 普通最大间隔时间（秒）
            burst_size (int, optional): 爆发阈值. Defaults to 0.
            rest_min (float, optional): 长休息最小时间. Defaults to 0.
            rest_max (float, optional): 长休息最大时间. Defaults to 0.
        """
        self.logger = logging.getLogger("DelayManager")
        self.normal_min = normal_min
        self.normal_max = normal_max

        # 爆发模式配置
        self.burst_size = burst_size
        self.rest_min = rest_min
        self.rest_max = rest_max

        # 内部计数器
        self._current_count = 0

    def wait_and_check_stop(self, stop_event: Event) -> bool:
        """
        计算需要等待的时间并执行等待

        Returns:
            bool: 如果收到停止信号(需要中断任务)返回 True，否则返回 False
        """
        if stop_event.is_set():
            self.logger.info("任务被用户手动停止。")
            return True
        
        self._current_count += 1

        # 判断是否触发长休息
        is_long_rest = False
        if self.burst_size > 1 and (self._current_count % self.burst_size == 0):
            is_long_rest = True

        delay = 0.0
        if is_long_rest:
            delay = random.uniform(self.rest_min, self.rest_max)
            self.logger.info(f"⚡ 已连续发送 {self.burst_size} 条，进入爆发后休息: {delay:.2f} 秒...")
        else:
            delay = random.uniform(self.normal_min, self.normal_max)
            self.logger.info(f"等待 {delay:.2f} 秒...")

        if stop_event.wait(timeout=delay):
            self.logger.info("在等待期间接收到停止信号，立即终止。")
            return True
        
        return False