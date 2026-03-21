import random
import logging
from threading import Event

class DelayManager:
    """
    发送节奏管理器 (Pacing / Delay Manager)
    
    设计意图：将“算时间”和“等时间”剥离成独立的控制模块。
    支持基础的随机波动延时，以及模拟真实人类批量操作习惯的“爆发-休息”模式。
    """
    def __init__(
        self,
        normal_min: float,
        normal_max: float,
        burst_size: int = 0,
        rest_min: float = 0,
        rest_max: float = 0
    ):
        """
        Args:
            normal_min (float): 普通间隔的随机下界（秒）
            normal_max (float): 普通间隔的随机上界（秒）
            burst_size (int): 爆发阈值，每发 N 条触发一次长休息。<=1 时表示禁用爆发模式。
            rest_min (float): 休息时间的随机下界（秒）
            rest_max (float): 休息时间的随机上界（秒）
        """
        self.logger = logging.getLogger("DelayManager")

        # 基础随机延迟配置
        self.normal_min = normal_min
        self.normal_max = normal_max

        # 爆发模式配置
        self.burst_size = burst_size
        self.rest_min = rest_min
        self.rest_max = rest_max

        # 内部计数器: 记录当前周期内已度过了多少次发送延时
        self._current_count = 0

        if self.burst_size > 1:
            self.logger.info(f"🚀 爆发模式已启用: 每 {self.burst_size} 条休息 {self.rest_min}-{self.rest_max} 秒")
        else:
            self.logger.debug(f"爆发模式未启用 (阈值: {self.burst_size})")

    def wait_and_check_stop(self, stop_event: Event) -> bool:
        """
        计算下一跳的等待时间并执行物理阻塞。

        Returns:
            bool: 如果在等待期间收到中断指令（即外部将 stop_event 置为 True），返回 True；否则返回 False。
        """
        if stop_event.is_set():
            return True

        # 指针步进
        self._current_count += 1

        # 判断本轮是短休还是长休
        is_long_rest = False
        if self.burst_size > 1 and (self._current_count % self.burst_size == 0):
            is_long_rest = True

        # 计算
        delay = 0.0
        if is_long_rest:
            delay = random.uniform(self.rest_min, self.rest_max)
            self.logger.info(f"⚡ 已连续发送 {self.burst_size} 条，进入爆发后休息: {delay:.2f} 秒...")
        else:
            delay = random.uniform(self.normal_min, self.normal_max)
            self.logger.info(f"等待 {delay:.2f} 秒...")

        if stop_event.wait(timeout=delay):
            self.logger.info("在等待期间接收到停止信号，立即终止延时策略。")
            return True
        
        return False