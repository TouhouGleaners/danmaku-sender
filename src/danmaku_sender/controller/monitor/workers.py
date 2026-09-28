import logging
import random
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import Signal

from danmaku_sender.config import ApiAuthConfig
from danmaku_sender.controller.concurrency import WorkerThread
from danmaku_sender.repo.bili_api_client import BiliApiClient
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.runtime.infra.platform import KeepSystemAwake
from danmaku_sender.service.danmaku_verifier import DanmakuVerifier
from danmaku_sender.types.models.common import MonitorStats, VideoTarget

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MonitorSample:
    """一个核销目标 (bvid, cid)，来自数据库。

    标题/分P 由 UI 从队列反查补齐，核销本身不需要。
    """

    bvid: str
    cid: int

    @property
    def target(self) -> VideoTarget:
        return VideoTarget(bvid=self.bvid, cid=self.cid)


class QueueMonitorWorker(WorkerThread):
    """队列监视 Worker：按间隔轮询在线核销并 emit，不写 QueueState。

    核销范围每轮从数据库读（get_recorded_targets），不碰队列状态。
    """

    targetStatsUpdated = Signal(str, int, object)  # (bvid, cid, MonitorStats)
    targetVerifyFailed = Signal(str, int)          # (bvid, cid)：本轮核销失败
    overallStatsUpdated = Signal(object)           # MonitorStats 合计
    statusUpdated = Signal(str)
    monitorFailed = Signal(str)                    # 异常终止原因（非用户停止）
    monitorFinished = Signal()
    ending = Signal(object)                        # run() 退出时 emit(self)，供主线程清理

    def __init__(
        self,
        auth_config: ApiAuthConfig,
        history_manager: HistoryManager,
        stop_event: threading.Event,
        baseline: float = 0.0,
        poll_interval: float = 60.0,
        prevent_sleep: bool = True,
        send_done: threading.Event | None = None,
        post_send_watch_seconds: float = 300.0,
        parent=None,
    ):
        super().__init__(parent)
        self.auth_config = auth_config
        self.history_manager = history_manager
        self.stop_event = stop_event
        self.baseline = baseline
        self.poll_interval = max(1.0, poll_interval)
        self.prevent_sleep = prevent_sleep
        # 「发送+监视」才传：发送结束后再盯 post_send_watch_seconds 自动停。
        # 传 None 表示独立监视，跑到用户手动停为止。
        self.send_done = send_done
        self.post_send_watch_seconds = post_send_watch_seconds

    @property
    def targets(self) -> list[MonitorSample]:
        """本轮核销范围：数据库里 baseline 后有记录的目标。"""
        try:
            rows = self.history_manager.get_recorded_targets(self.baseline)
        except Exception as e:
            logger.warning(f"读取核销范围失败，本轮跳过: {e}", exc_info=True)
            return []
        return [MonitorSample(bvid=bvid, cid=cid) for bvid, cid in rows]

    def run(self):
        failed = False
        try:
            with KeepSystemAwake(self.prevent_sleep):
                deadline: float | None = None
                while not self.stop_event.is_set():
                    if deadline is None and self.send_done is not None and self.send_done.is_set():
                        deadline = time.monotonic() + self.post_send_watch_seconds
                    if deadline is not None and time.monotonic() >= deadline:
                        logger.info("发送后监视时限已到，队列监视终止。")
                        break

                    self._run_round()

                    # 等待既不超下一轮间隔，也不越过监视截止
                    wait_seconds = self.poll_interval
                    if deadline is not None:
                        wait_seconds = min(wait_seconds, max(0.0, deadline - time.monotonic()))
                    if self.stop_event.wait(wait_seconds):
                        logger.info("收到停止信号，队列监视终止。")
                        break
        except Exception as e:
            failed = True
            logger.error(f"队列监视发生未预期异常: {e}", exc_info=True)
            self.statusUpdated.emit(f"监视器异常终止: {e}")
            self.monitorFailed.emit(str(e))
        finally:
            self.monitorFinished.emit()
            self.ending.emit(self)
            if failed:
                logger.warning("队列监视已异常退出，需人工重新启动。")

    def _run_round(self):
        samples = self.targets
        if not samples:
            # 开跑初期数据库可能是空的（还没发出存证），安静等下一轮
            logger.debug("本轮无存证目标，跳过核销。")
            return

        overall: MonitorStats = {"total": 0, "verified": 0, "pending": 0, "lost": 0}

        logger.info(f"🔍 在线核销开始，共 {len(samples)} 个分P。")
        with BiliApiClient.from_config(self.auth_config) as client:
            verifier = DanmakuVerifier(api_client=client, history_manager=self.history_manager)

            for i, sample in enumerate(samples):
                if self.stop_event.is_set():
                    return

                try:
                    result = verifier.verify_cid(sample.cid, mark_lost=False)
                    logger.info(
                        f"[{sample.bvid} {sample.cid}] 对账完成: 核销 {result['verified']} 条，"
                        f"在线共 {result['total_checked']} 条。"
                    )
                except Exception as e:
                    # 本轮不发统计；通知 UI 丢弃该目标缓存，与 Worker 合计口径一致
                    logger.warning(f"[{sample.bvid} {sample.cid}] 在线核销失败，跳过: {e}")
                    self.targetVerifyFailed.emit(sample.bvid, sample.cid)
                    continue

                stats = self._stats_for(sample.target)
                self.targetStatsUpdated.emit(sample.bvid, sample.cid, stats)
                overall["total"] += stats.get("total", 0)
                overall["verified"] += stats.get("verified", 0)
                overall["pending"] += stats.get("pending", 0)
                overall["lost"] += stats.get("lost", 0)

                if i + 1 < len(samples) and self.stop_event.wait(random.uniform(1.0, 3.0)):
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

    def _stats_for(self, target: VideoTarget) -> MonitorStats:
        stats = self.history_manager.get_stats_for_target(target=target, baseline=self.baseline)
        return {
            "total": stats.get("total", 0),
            "verified": stats.get("verified", 0),
            "pending": stats.get("pending", 0),
            "lost": stats.get("lost", 0),
        }
