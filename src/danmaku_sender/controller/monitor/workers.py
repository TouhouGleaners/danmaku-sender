import logging
import random
import threading

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

_MONITORABLE = (
    TaskStatus.COMPLETED,
    TaskStatus.RUNNING,
    TaskStatus.FAILED,
    TaskStatus.PAUSED,
)

# (task_id, target, label)
MonitorTargetItem = tuple[str, VideoTarget, str]


class QueueMonitorWorker(WorkerThread):
    """队列监视 Worker：薄壳，按间隔轮询在线核销并 emit，不写 QueueState。

    只读 AppState 采样当前可监视任务与配置；禁止在本线程改共享状态。
    """

    taskStatsUpdated = Signal(str, object)   # (task_id, MonitorStats)
    overallStatsUpdated = Signal(object)     # MonitorStats 合计
    statusUpdated = Signal(str)
    monitorFinished = Signal()

    def __init__(
        self,
        state: AppState,
        auth_config: ApiAuthConfig,
        history_manager: HistoryManager,
        stop_event: threading.Event,
        parent=None,
    ):
        super().__init__(parent)
        self.state = state
        self.auth_config = auth_config
        self.history_manager = history_manager
        self.stop_event = stop_event

    @property
    def targets(self) -> list[MonitorTargetItem]:
        """当前队列中可监视的任务采样（只读，走 QueueState 快照）"""
        items: list[MonitorTargetItem] = []
        for task in self.state.queue_state.tasks:
            if task.status not in _MONITORABLE:
                continue
            if task.p_index > 0 and task.p_title:
                label = f"P{task.p_index} - {task.p_title}"
            else:
                label = task.p_title or task.target.display_string
            items.append((task.task_id, task.target, label))
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
        try:
            with KeepSystemAwake(True):
                while not self.stop_event.is_set():
                    self._run_round()
                    if self.stop_event.wait(self.poll_interval_seconds):
                        logger.info("收到停止信号，队列监视终止。")
                        break
        except Exception as e:
            logger.error(f"队列监视发生未预期异常: {e}", exc_info=True)
        finally:
            self.monitorFinished.emit()

    def _run_round(self):
        targets = list(self.targets)
        if not targets:
            self.statusUpdated.emit("监视器：无可监视任务")
            return

        baseline = self.stats_baseline
        overall: MonitorStats = {"total": 0, "verified": 0, "pending": 0, "lost": 0}

        logger.info(f"🔍 在线核销开始，共 {len(targets)} 个分P。")
        with BiliApiClient.from_config(self.auth_config) as client:
            verifier = DanmakuVerifier(api_client=client, history_manager=self.history_manager)

            for i, (task_id, target, label) in enumerate(targets):
                if self.stop_event.is_set():
                    return

                try:
                    result = verifier.verify_cid(target.cid, mark_lost=False)
                    logger.info(
                        f"[{label}] 对账完成: 核销 {result['verified']} 条，"
                        f"在线共 {result['total_checked']} 条。"
                    )
                except Exception as e:
                    logger.warning(f"[{label}] 在线核销失败，跳过: {e}")

                stats = self._stats_for(target, baseline)
                self.taskStatsUpdated.emit(task_id, stats)
                overall["total"] += stats.get("total", 0)
                overall["verified"] += stats.get("verified", 0)
                overall["pending"] += stats.get("pending", 0)
                overall["lost"] += stats.get("lost", 0)

                if i + 1 < len(targets) and self.stop_event.wait(random.uniform(1.0, 3.0)):
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
