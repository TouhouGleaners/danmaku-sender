import logging
import random
import threading
from dataclasses import dataclass

from PySide6.QtCore import Signal

from danmaku_sender.config import ApiAuthConfig
from danmaku_sender.controller.concurrency import WorkerThread
from danmaku_sender.repo.bili_api_client import BiliApiClient
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.runtime.infra.platform import KeepSystemAwake
from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.service.danmaku_verifier import DanmakuVerifier
from danmaku_sender.types.models.common import MonitorStats, VideoTarget
from danmaku_sender.types.models.queue import TaskStatus

logger = logging.getLogger(__name__)

MONITORABLE_STATUSES: frozenset[TaskStatus] = frozenset(
    (
        TaskStatus.COMPLETED,
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
        TaskStatus.PAUSED,
    )
)


@dataclass(frozen=True)
class MonitorSample:
    """一轮监视采样：字段在采样时拷贝，与后续队列编辑隔离。"""

    task_id: str
    bvid: str
    cid: int
    title: str
    label: str

    @property
    def target(self) -> VideoTarget:
        return VideoTarget(bvid=self.bvid, cid=self.cid, title=self.title)


class QueueMonitorWorker(WorkerThread):
    """队列监视 Worker：薄壳，按间隔轮询在线核销并 emit，不写 QueueState。

    只读 AppState 采样；采样结果为不可变 MonitorSample。
    """

    taskStatsUpdated = Signal(str, object)   # (task_id, MonitorStats)
    taskVerifyFailed = Signal(str)           # task_id：本轮核销失败
    overallStatsUpdated = Signal(object)     # MonitorStats 合计
    statusUpdated = Signal(str)
    monitorFailed = Signal(str)              # 异常终止原因（非用户停止）
    monitorFinished = Signal()
    ending = Signal(object)                  # run() 退出时 emit(self)，供主线程清理

    def __init__(
        self,
        state: AppState,
        auth_config: ApiAuthConfig,
        history_manager: HistoryManager,
        stop_event: threading.Event,
        prevent_sleep: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.state = state
        self.auth_config = auth_config
        self.history_manager = history_manager
        self.stop_event = stop_event
        self.prevent_sleep = prevent_sleep

    @property
    def targets(self) -> list[MonitorSample]:
        """当前队列中可监视任务的不可变采样（status 在 QueueState 锁内定死）。"""
        items: list[MonitorSample] = []
        for snap in self.state.queue_state.snapshots(MONITORABLE_STATUSES):
            spec = snap.spec
            if spec.p_index > 0 and spec.p_title:
                label = f"P{spec.p_index} - {spec.p_title}"
            else:
                label = spec.p_title or spec.target.title or spec.target.bvid
            items.append(
                MonitorSample(
                    task_id=spec.task_id,
                    bvid=spec.target.bvid,
                    cid=spec.target.cid,
                    title=spec.target.title,
                    label=label,
                )
            )
        return items

    @property
    def stats_baseline(self) -> float:
        return float(self.state.monitor_config.stats_baseline)

    @property
    def poll_interval_seconds(self) -> float:
        """轮询间隔（秒）；下一轮开始前读取，运行中改配置会生效"""
        try:
            value = float(self.state.monitor_config.refresh_interval)
        except (TypeError, ValueError):
            value = 60.0
        return max(1.0, value)

    def run(self):
        failed = False
        try:
            with KeepSystemAwake(self.prevent_sleep):
                while not self.stop_event.is_set():
                    self._run_round()
                    if self.stop_event.wait(self.poll_interval_seconds):
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
            self.statusUpdated.emit("监视器：无可监视任务")
            return

        baseline = self.stats_baseline
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
                        f"[{sample.label}] 对账完成: 核销 {result['verified']} 条，"
                        f"在线共 {result['total_checked']} 条。"
                    )
                except Exception as e:
                    # 本轮不发统计；通知 UI 丢弃该任务缓存，与 Worker 合计口径一致
                    logger.warning(f"[{sample.label}] 在线核销失败，跳过: {e}")
                    self.taskVerifyFailed.emit(sample.task_id)
                    continue

                stats = self._stats_for(sample.target, baseline)
                self.taskStatsUpdated.emit(sample.task_id, stats)
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

    def _stats_for(self, target: VideoTarget, baseline: float) -> MonitorStats:
        stats = self.history_manager.get_stats_for_target(target=target, baseline=baseline)
        return {
            "total": stats.get("total", 0),
            "verified": stats.get("verified", 0),
            "pending": stats.get("pending", 0),
            "lost": stats.get("lost", 0),
        }
