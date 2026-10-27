import logging
import random
import threading
from dataclasses import dataclass

from PySide6.QtCore import Signal

from danmaku_sender.config import ApiAuthConfig, NetworkPolicy
from danmaku_sender.controller.concurrency import WorkerThread
from danmaku_sender.infra.bilibili.bili_api_client import BiliApiClient
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.infra.platform import KeepSystemAwake
from danmaku_sender.service.danmaku_verifier import DanmakuVerifier
from danmaku_sender.types.models.common import MonitorStats, VideoTarget

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MonitorTarget:
    """一个核销目标 (bvid, cid)，来自数据库。

    标题/分P 由 UI 从队列反查补齐，核销本身不需要。
    """

    bvid: str
    cid: int


class QueueMonitorWorker(WorkerThread):
    """队列监视 Worker：按间隔轮询在线核销并 emit，不写 QueueState。

    核销范围每轮从数据库读（get_recorded_targets），不碰队列状态。
    """

    # cid 用 object 传：Qt 信号的 int 是 32 位，B 站新视频的 cid 会溢出绕回
    targetStatsUpdated = Signal(str, object, object)  # (bvid, cid, MonitorStats)
    targetVerifyFailed = Signal(str, object)          # (bvid, cid)：本轮核销失败
    overallStatsUpdated = Signal(object)              # MonitorStats 合计
    statusUpdated = Signal(str)
    monitorFailed = Signal(str)                       # 异常终止原因（非用户停止）
    monitorFinished = Signal()
    ending = Signal(object)                           # run() 退出时 emit(self)，供主线程清理

    def __init__(
        self,
        auth: ApiAuthConfig,
        network: NetworkPolicy,
        history_manager: HistoryManager,
        stop_event: threading.Event,
        baseline: float = 0.0,
        poll_interval: float = 60.0,
        prevent_sleep: bool = True,
        parent=None,
    ):
        """初始化队列监视 Worker。

        Args:
            auth: 身份凭据。
            network: 传输策略。
            history_manager: 本地账本，核销范围取自这里。
            stop_event: 中止标记。
            baseline: 核销基线时间戳，0 表示全量历史。
            poll_interval: 轮询间隔（秒）。
            prevent_sleep: 监视期间是否阻止系统休眠。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.auth = auth
        self.network = network
        self.history_manager = history_manager
        self.stop_event = stop_event
        self.baseline = baseline
        self.poll_interval = max(1.0, poll_interval)
        self.prevent_sleep = prevent_sleep

    @property
    def targets(self) -> list[MonitorTarget]:
        """本轮核销范围：数据库里 baseline 后有记录的目标。"""
        rows = self.history_manager.get_recorded_targets(self.baseline)
        return [MonitorTarget(bvid=bvid, cid=cid) for bvid, cid in rows]

    def run(self):
        failed = False
        try:
            with KeepSystemAwake(self.prevent_sleep):
                while not self.stop_event.is_set():
                    self._inspect_targets()
                    if self._sleep(self.poll_interval):
                        logger.info("收到停止信号，队列监视终止。")
                        break
        except Exception as e:
            failed = True
            logger.exception("队列监视发生未预期异常")
            self.statusUpdated.emit(f"监视器异常终止: {e}")
            self.monitorFailed.emit(str(e))
        finally:
            self.monitorFinished.emit()
            self.ending.emit(self)
            if failed:
                logger.warning("队列监视已异常退出，需人工重新启动。")

    def _sleep(self, seconds: float) -> bool:
        """等待 seconds。返回 True = 收到停止信号。"""
        return self.stop_event.wait(seconds)

    def _inspect_targets(self):
        try:
            targets = self.targets
        except Exception as e:
            # 查询失败跳过本轮；状态栏同步说明，免得看着像空转
            logger.warning(f"读取发送记录失败，本轮跳过: {e}", exc_info=True)
            self.statusUpdated.emit("监视中（读取发送记录失败，本轮跳过）")
            return
        if not targets:
            # 开跑初期数据库可能是空的（还没发出存证），安静等下一轮
            logger.debug("本轮无存证目标，跳过核销。")
            return

        overall: MonitorStats = {"total": 0, "verified": 0, "pending": 0, "lost": 0}

        logger.info(f"🔍 在线核销开始，共 {len(targets)} 个分P。")
        with BiliApiClient(self.auth, self.network) as client:
            verifier = DanmakuVerifier(api_client=client, history_manager=self.history_manager)

            for i, target in enumerate(targets):
                if self.stop_event.is_set():
                    return

                stats = self._inspect_target(verifier, target)
                if stats is not None:
                    overall["total"] += stats.get("total", 0)
                    overall["verified"] += stats.get("verified", 0)
                    overall["pending"] += stats.get("pending", 0)
                    overall["lost"] += stats.get("lost", 0)

                if i + 1 < len(targets) and self._sleep(random.uniform(1.0, 3.0)):
                    return

        self.overallStatsUpdated.emit(overall)
        self.statusUpdated.emit(
            f"监视中 (存活: {overall['verified']} / 待验: {overall['pending']} / 疑似: {overall['lost']})"
        )
        logger.info(
            f"统计: 已发 {overall['total']} / 存活 {overall['verified']}"
            f" / 待验 {overall['pending']} / 疑似 {overall['lost']}"
        )
        logger.info("✅ 本轮在线核销结束。")

    def _inspect_target(
        self, verifier: DanmakuVerifier, target: MonitorTarget
    ) -> MonitorStats | None:
        """核查单个目标分P的存活并上报；失败返回 None。

        Args:
            verifier: 在线核销器。
            target: 待核查的目标分P。

        Returns:
            MonitorStats | None: 该目标的存活统计；核查失败返回 None。
        """
        try:
            result = verifier.verify_cid(target.cid, mark_lost=False)
            logger.info(
                f"[{target.bvid} {target.cid}] 对账完成: 核销 {result['verified']} 条，"
                f"在线共 {result['total_checked']} 条。"
            )
        except Exception as e:
            # 单目标失败不中断整轮；本轮不发统计，通知 UI 丢弃该目标缓存
            logger.warning(f"[{target.bvid} {target.cid}] 在线核销失败，跳过: {e}")
            self.targetVerifyFailed.emit(target.bvid, target.cid)
            return None

        stats = self._stats_for(VideoTarget(bvid=target.bvid, cid=target.cid))
        self.targetStatsUpdated.emit(target.bvid, target.cid, stats)
        return stats

    def _stats_for(self, target: VideoTarget) -> MonitorStats:
        stats = self.history_manager.get_stats_for_target(target=target, baseline=self.baseline)
        return {
            "total": stats.get("total", 0),
            "verified": stats.get("verified", 0),
            "pending": stats.get("pending", 0),
            "lost": stats.get("lost", 0),
        }
