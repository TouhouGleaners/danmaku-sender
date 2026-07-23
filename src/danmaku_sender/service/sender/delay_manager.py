import random
import logging
from threading import Event


class DelayManager:
    """
    发送节奏管理器 (Pacing / Delay Manager)

    支持基础的随机波动延时，以及模拟人类批量操作习惯的“爆发-休息”模式。
    """
    def __init__(
        self,
        normal_min: float,
        normal_max: float,
        burst_enabled: bool = False,
        burst_size: int = 3,
        rest_min: float = 0,
        rest_max: float = 0,
    ):
        """
        Args:
            normal_min (float): 普通间隔的随机下界（秒）
            normal_max (float): 普通间隔的随机上界（秒）
            burst_enabled (bool): 是否启用爆发模式。
            burst_size (int): 爆发阈值，每发 N 条触发一次长休息。
            rest_min (float): 休息时间的随机下界（秒）
            rest_max (float): 休息时间的随机上界（秒）
        """
        self.logger = logging.getLogger("App.Sender.Delay")

        # 基础随机延迟配置
        self.normal_min = normal_min
        self.normal_max = normal_max

        # 爆发模式配置
        self.burst_enabled = burst_enabled
        self.burst_size = burst_size
        self.rest_min = rest_min
        self.rest_max = rest_max

        # 内部计数器: 记录当前周期内已度过了多少次发送延时
        self._current_count = 0

        if self.burst_enabled:
            self.logger.info(f"🚀 爆发模式已启用: 每 {self.burst_size} 条休息 {self.rest_min}-{self.rest_max} 秒")
        else:
            self.logger.debug("爆发模式未启用")

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
        if self.burst_enabled and (self._current_count % self.burst_size == 0):
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

    @staticmethod
    def calc_eta(attempted: int, total: int, burst_enabled: bool, burst_size: int, avg_normal: float, avg_rest: float) -> float:
        """
        计算剩余等待时间 (O(1))。

        契约 (Contract):
        1. 延时发生在发送动作之后，因此最后一条弹幕发完不产生延时，总延时次数为 total - 1。
        2. 延时的物理索引从 1 开始（第 k 条弹幕发完后的延时索引为 k）。
        3. 仅当延时索引能被 burst_size 整除时，触发大休息 (avg_rest)。
        """
        # 未启用爆发模式时，视为无爆发
        if not burst_enabled:
            burst_size = 1

        # 统一处理 0 和 1 进度：
        # 准备开始(0)和准备发第1条(1)时，前面都没有发生过延时，
        # 其后续的延时索引区间都是 [1, total - 1]。
        current_k = max(1, attempted)
        remaining_waits = total - current_k

        if remaining_waits <= 0:
            return 0.0

        if burst_size == 1:
            return remaining_waits * avg_normal

        # 在闭区间 [current_k, total - 1] 中，计算能被 burst_size 整除的元素个数
        rest_count = (total - 1) // burst_size - (current_k - 1) // burst_size
        normal_count = remaining_waits - rest_count

        return (normal_count * avg_normal) + (rest_count * avg_rest)