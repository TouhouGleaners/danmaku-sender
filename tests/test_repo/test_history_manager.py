"""HistoryManager 单元测试 — 存证/核销/标记丢失/统计

包含 2026-09 存证静默丢失事故的回归测试：发送成功后记录必须真实落库可查。
"""
import sqlite3

import pytest

from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.types.models.common import DanmakuStatus, VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku


@pytest.fixture
def target() -> VideoTarget:
    return VideoTarget(bvid="BV1xx411c7mD", cid=1001)


@pytest.fixture
def hm(tmp_path) -> HistoryManager:
    return HistoryManager(tmp_path / "history.db")


def _record(hm: HistoryManager, target: VideoTarget, dmid: str, msg: str = "弹幕", task_id: str = "t1") -> None:
    hm.record_danmaku(task_id, target, Danmaku(msg=msg, progress=1000), dmid)


class TestRecordDanmaku:
    """存证回归：发送成功后记录必须真实落库"""

    def test_record_persists_row(self, hm, target):
        _record(hm, target, "dm1", task_id="t7")
        row = sqlite3.connect(hm.db_path).execute(
            "SELECT dmid, cid, status, task_id FROM sent_danmaku WHERE dmid='dm1'"
        ).fetchone()
        assert row == ("dm1", 1001, DanmakuStatus.PENDING.value, "t7")

    def test_record_conflict_ignored(self, hm, target):
        """同 dmid 二次存证被忽略，不产生重复行"""
        _record(hm, target, "dm1")
        _record(hm, target, "dm1")
        n = sqlite3.connect(hm.db_path).execute("SELECT COUNT(*) FROM sent_danmaku").fetchone()[0]
        assert n == 1

    def test_record_without_dmid_skipped(self, hm, target):
        """POST 响应缺 dmid 时跳过存证"""
        _record(hm, target, "")
        n = sqlite3.connect(hm.db_path).execute("SELECT COUNT(*) FROM sent_danmaku").fetchone()[0]
        assert n == 0

    def test_init_is_idempotent(self, hm, target):
        """重启等场景下重复初始化不得破坏既有数据"""
        _record(hm, target, "dm1")
        hm2 = HistoryManager(hm.db_path)
        assert hm2.get_stats(1001) == (1, 0, 0)


class TestVerifyAndLost:
    """核销与标记丢失"""

    def test_verify_flips_pending_to_verified(self, hm, target):
        _record(hm, target, "dm1")
        _record(hm, target, "dm2")
        assert hm.verify_dmids(["dm1", "dm-not-exist"]) == 1
        assert hm.get_stats(1001) == (2, 1, 0)

    def test_verify_does_not_touch_verified(self, hm, target):
        """已存活的弹幕不会被重复核销"""
        _record(hm, target, "dm1")
        hm.verify_dmids(["dm1"])
        assert hm.verify_dmids(["dm1"]) == 0

    def test_mark_as_lost_excludes_verified(self, hm, target):
        _record(hm, target, "dm1")
        _record(hm, target, "dm2")
        hm.verify_dmids(["dm1"])
        assert hm.mark_as_lost(1001, ["dm1"]) == 1  # 仅未在线的 dm2
        assert hm.get_stats(1001) == (2, 1, 1)

    def test_mark_as_lost_keeps_row_present(self, hm, target):
        """丢失是标记而非删除"""
        _record(hm, target, "dm1")
        hm.mark_as_lost(1001, [])
        n = sqlite3.connect(hm.db_path).execute("SELECT COUNT(*) FROM sent_danmaku").fetchone()[0]
        assert n == 1


class TestTargetsWithEvidence:
    """核销范围来自存证，不是队列

    发送与监视互不认识，只通过数据库交接：
    数据库里有的才需要对账，未发送的不是成员。
    """

    def test_empty_ledger_returns_empty(self, hm):
        assert hm.get_recorded_targets() == []

    def test_returns_targets_holding_evidence(self, hm, target):
        other = VideoTarget(bvid="BV2xx", cid=2002)
        _record(hm, target, "dm1")
        assert hm.get_recorded_targets() == [("BV1xx411c7mD", 1001)]
        _record(hm, other, "dm2")
        assert hm.get_recorded_targets() == [("BV1xx411c7mD", 1001), ("BV2xx", 2002)]

    def test_dedupes_targets(self, hm, target):
        _record(hm, target, "dm1")
        _record(hm, target, "dm2")
        assert hm.get_recorded_targets() == [("BV1xx411c7mD", 1001)]

    def test_baseline_filters_out_old_evidence(self, hm, target):
        import time
        _record(hm, target, "dm1")
        conn = sqlite3.connect(hm.db_path)
        conn.execute("UPDATE sent_danmaku SET ctime=? WHERE dmid='dm1'", (time.time() - 3600,))
        conn.commit()
        conn.close()
        assert hm.get_recorded_targets() == [("BV1xx411c7mD", 1001)]
        assert hm.get_recorded_targets(baseline=time.time() - 60) == []

    def test_ordered_by_first_evidence(self, hm, target):
        """行序跟首条存证时间一致（跟发送顺序），不随后续写入改变"""
        import time
        other = VideoTarget(bvid="BV2xx", cid=2002)
        _record(hm, target, "dm1")
        _record(hm, other, "dm2")
        _record(hm, target, "dm3")  # 第二个目标晚发，但不改变谁排前面
        conn = sqlite3.connect(hm.db_path)
        conn.execute("UPDATE sent_danmaku SET ctime=? WHERE dmid='dm2'", (time.time() + 10,))
        conn.commit()
        conn.close()
        assert hm.get_recorded_targets() == [("BV1xx411c7mD", 1001), ("BV2xx", 2002)]


class TestStatsAndDedup:
    """统计与断点续传查重"""
    def test_get_stats_with_baseline(self, hm, target):
        _record(hm, target, "dm1")
        import time
        conn = sqlite3.connect(hm.db_path)
        conn.execute("UPDATE sent_danmaku SET ctime=? WHERE dmid='dm1'", (time.time() - 3600,))
        conn.commit()
        conn.close()
        _record(hm, target, "dm2")

        assert hm.get_stats(1001, stats_baseline=time.time() - 60) == (1, 0, 0)
        assert hm.get_stats(1001) == (2, 0, 0)

    def test_count_records_for_dedup(self, hm, target):
        """断点续传计数：PENDING/VERIFIED 计入，LOST 不计入（可重发）"""
        dm = Danmaku(msg="重复弹幕", progress=1000)
        _record(hm, target, "dm1", msg="重复弹幕")
        _record(hm, target, "dm2", msg="重复弹幕")
        assert hm.count_records(target, dm) == 2      # PENDING 计入
        hm.verify_dmids(["dm1"])
        assert hm.count_records(target, dm) == 2      # VERIFIED 计入
        hm.mark_as_lost(1001, ["dm1"])                # dm2 被标记丢失
        assert hm.count_records(target, dm) == 1      # LOST 不计入（只剩 VERIFIED 的 dm1）
