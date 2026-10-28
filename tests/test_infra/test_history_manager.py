"""HistoryManager 单元测试 — 存证/核销/标记丢失/统计

包含 2026-09 存证静默丢失事故的回归测试：发送成功后记录必须真实落库可查。
"""
import sqlite3

import pytest

from danmaku_sender.config import SenderConfig
from danmaku_sender.infra.persistence.history_manager import (
    SCHEMA_VERSION,
    HistoryManager,
)
from danmaku_sender.infra.persistence.orm_models import SentDanmaku
from danmaku_sender.types.models.common import DanmakuStatus, TaskMeta, VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import TaskDefinition, TaskStatus


@pytest.fixture
def target() -> VideoTarget:
    return VideoTarget(bvid="BV1xx411c7mD", cid=1001)


@pytest.fixture
def hm(tmp_path) -> HistoryManager:
    return HistoryManager(tmp_path / "history.db")


def _record(hm: HistoryManager, target: VideoTarget, dmid: str, msg: str = "弹幕", task_id: str = "t1") -> None:
    hm.record_danmaku(task_id, target, Danmaku(msg=msg, progress=1000), dmid)


def _task_definition(
    task_id: str = "t1",
    bvid: str = "BV1xx",
    cid: int = 1001,
    video_title: str = "标题",
    part_title: str = "分P",
) -> TaskDefinition:
    return TaskDefinition(
        task_id=task_id,
        target=VideoTarget(bvid=bvid, cid=cid),
        meta=TaskMeta(video_title=video_title, part_page=2, part_title=part_title),
        danmakus=(Danmaku(msg="x", progress=0),),
        config=SenderConfig.PacingConfig(min_delay=0.1, max_delay=0.2).to_task_config(),
    )


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

    def test_record_without_dmid_raises(self, hm, target):
        """无 dmid 的存证不得静默丢弃"""
        with pytest.raises(ValueError):
            _record(hm, target, "")

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


class TestTaskRecord:
    """任务记录：身份与运行态落账，供任务级历史对账"""

    def test_upsert_inserts_then_updates(self, hm):
        definition = _task_definition()
        hm.upsert_task(definition, TaskStatus.RUNNING)
        row = hm.get_task("t1")
        assert row is not None
        assert row["bvid"] == "BV1xx"
        assert row["cid"] == 1001
        assert row["video_title"] == "标题"
        assert row["part_page"] == 2
        assert row["status"] == "RUNNING"

        hm.upsert_task(definition, TaskStatus.COMPLETED)
        row = hm.get_task("t1")
        assert row is not None
        assert row["status"] == "COMPLETED"
        n = sqlite3.connect(hm.db_path).execute("SELECT COUNT(*) FROM task_record").fetchone()[0]
        assert n == 1

    def test_get_task_missing_returns_none(self, hm):
        assert hm.get_task("nope") is None

    def test_task_record_and_evidence_share_task_id(self, hm, target):
        """同一条任务：弹幕存证与任务记录靠 task_id 对上"""
        definition = _task_definition(task_id="任务归属-8f3c")
        hm.upsert_task(definition, TaskStatus.COMPLETED)
        _record(hm, target, "dm1", task_id="任务归属-8f3c")

        assert hm.get_task("任务归属-8f3c") is not None
        rows = sqlite3.connect(hm.db_path).execute(
            "SELECT task_id FROM sent_danmaku WHERE dmid='dm1'"
        ).fetchall()
        assert rows == [("任务归属-8f3c",)]


class TestTaskQueries:
    """任务级查询：清单、存活聚合与搜索命中"""

    @staticmethod
    def _set_created_at(hm: HistoryManager, task_id: str, created_at: float) -> None:
        conn = sqlite3.connect(hm.db_path)
        conn.execute("UPDATE task_record SET created_at=? WHERE task_id=?", (created_at, task_id))
        conn.commit()
        conn.close()

    @staticmethod
    def _set_ctime(hm: HistoryManager, dmid: str, ctime: float) -> None:
        conn = sqlite3.connect(hm.db_path)
        conn.execute("UPDATE sent_danmaku SET ctime=? WHERE dmid=?", (ctime, dmid))
        conn.commit()
        conn.close()

    def test_list_tasks_orders_by_start_time(self, hm):
        hm.upsert_task(_task_definition(task_id="t2"), TaskStatus.RUNNING)
        hm.upsert_task(_task_definition(task_id="t1"), TaskStatus.RUNNING)
        self._set_created_at(hm, "t2", 2000.0)
        self._set_created_at(hm, "t1", 1000.0)

        assert [row["task_id"] for row in hm.list_tasks()] == ["t1", "t2"]

    def test_get_task_stats_groups_by_task(self, hm, target):
        _record(hm, target, "dm1", task_id="t1")
        _record(hm, target, "dm2", task_id="t1")
        _record(hm, target, "dm3", task_id="t2")
        hm.verify_dmids(["dm1"])

        stats = hm.get_task_stats()
        assert stats["t1"] == {"total": 2, "verified": 1, "pending": 1, "lost": 0}
        assert stats["t2"] == {"total": 1, "verified": 0, "pending": 1, "lost": 0}

    def test_get_task_stats_counts_lost(self, hm, target):
        _record(hm, target, "dm1", task_id="t1")
        _record(hm, target, "dm2", task_id="t1")
        hm.verify_dmids(["dm1"])
        hm.mark_as_lost(1001, ["dm1"])

        assert hm.get_task_stats()["t1"] == {"total": 2, "verified": 1, "pending": 0, "lost": 1}

    def test_get_task_stats_ignores_rows_without_task(self, hm, target):
        """task_id 为空的旧存证不归属任何任务"""
        _record(hm, target, "dm1", task_id="t1")
        conn = sqlite3.connect(hm.db_path)
        conn.execute("UPDATE sent_danmaku SET task_id=NULL WHERE dmid='dm1'")
        conn.commit()
        conn.close()

        assert hm.get_task_stats() == {}

    def test_get_task_stats_respects_baseline(self, hm, target):
        import time
        _record(hm, target, "dm1", task_id="t1")
        _record(hm, target, "dm2", task_id="t1")
        self._set_ctime(hm, "dm1", time.time() - 3600)

        assert hm.get_task_stats(baseline=time.time() - 60)["t1"] == {
            "total": 1, "verified": 0, "pending": 1, "lost": 0,
        }
        assert hm.get_task_stats()["t1"]["total"] == 2

    def test_search_by_title_hit(self, hm):
        hm.upsert_task(_task_definition(task_id="t1", video_title="宝可梦补档"), TaskStatus.COMPLETED)
        hm.upsert_task(_task_definition(task_id="t2", video_title="无关标题"), TaskStatus.COMPLETED)

        hits = hm.search_tasks("宝可梦")
        assert [h["task_id"] for h in hits] == ["t1"]
        assert hits[0]["title_hit"] is True
        assert hits[0]["msg_hits"] == 0

    def test_search_by_bvid_hit(self, hm):
        hm.upsert_task(_task_definition(task_id="t1", bvid="BV1pkq"), TaskStatus.COMPLETED)

        hits = hm.search_tasks("pkq")
        assert [h["task_id"] for h in hits] == ["t1"]
        assert hits[0]["title_hit"] is True

    def test_search_by_msg_counts_hits(self, hm, target):
        hm.upsert_task(_task_definition(task_id="t1"), TaskStatus.COMPLETED)
        _record(hm, target, "dm1", msg="宝可梦真好玩", task_id="t1")
        _record(hm, target, "dm2", msg="宝可梦再来", task_id="t1")
        _record(hm, target, "dm3", msg="无关内容", task_id="t1")

        hits = hm.search_tasks("宝可梦")
        assert [h["task_id"] for h in hits] == ["t1"]
        assert hits[0]["title_hit"] is False
        assert hits[0]["msg_hits"] == 2

    def test_search_reports_both_hit_sources(self, hm, target):
        hm.upsert_task(_task_definition(task_id="t1", video_title="宝可梦补档"), TaskStatus.COMPLETED)
        _record(hm, target, "dm1", msg="宝可梦", task_id="t1")

        hits = hm.search_tasks("宝可梦")
        assert hits[0]["title_hit"] is True
        assert hits[0]["msg_hits"] == 1

    def test_search_ignores_evidence_without_task(self, hm, target):
        """task_id 为空的旧存证搜不出来"""
        hm.upsert_task(_task_definition(task_id="t1", video_title="无关标题"), TaskStatus.COMPLETED)
        _record(hm, target, "dm1", msg="宝可梦", task_id="t1")
        conn = sqlite3.connect(hm.db_path)
        conn.execute("UPDATE sent_danmaku SET task_id=NULL WHERE dmid='dm1'")
        conn.commit()
        conn.close()

        assert hm.search_tasks("宝可梦") == []

    def test_search_empty_keyword_returns_empty(self, hm):
        hm.upsert_task(_task_definition(task_id="t1"), TaskStatus.COMPLETED)
        assert hm.search_tasks("") == []

    def test_search_treats_wildcards_literally(self, hm):
        """% 与 _ 按字面匹配，不当通配符"""
        hm.upsert_task(_task_definition(task_id="t1", video_title="完成度 100%"), TaskStatus.COMPLETED)
        hm.upsert_task(_task_definition(task_id="t2", video_title="完成度 1000"), TaskStatus.COMPLETED)

        assert [h["task_id"] for h in hm.search_tasks("100%")] == ["t1"]

    def test_search_title_hit_follows_database_collation(self, hm):
        """命中来源与筛选同口径：标题命中由同一条 SQL 条件判定"""
        hm.upsert_task(_task_definition(task_id="t1", video_title="BV1Pkq 补档"), TaskStatus.COMPLETED)

        hits = hm.search_tasks("pkq")
        assert [h["task_id"] for h in hits] == ["t1"]
        assert hits[0]["title_hit"] is True

    def test_search_orders_by_start_time(self, hm):
        hm.upsert_task(_task_definition(task_id="t2", video_title="宝可梦"), TaskStatus.COMPLETED)
        hm.upsert_task(_task_definition(task_id="t1", video_title="宝可梦"), TaskStatus.COMPLETED)
        self._set_created_at(hm, "t2", 2000.0)
        self._set_created_at(hm, "t1", 1000.0)

        assert [h["task_id"] for h in hm.search_tasks("宝可梦")] == ["t1", "t2"]

    def test_query_history_filters_by_task(self, hm, target):
        _record(hm, target, "dm1", task_id="t1")
        _record(hm, target, "dm2", task_id="t2")

        assert [row["dmid"] for row in hm.query_history(task_id="t1")] == ["dm1"]


class TestMigration:
    """老库升级：补齐缺失的列与索引，且重复初始化幂等"""

    def test_upgrades_legacy_schema(self, tmp_path, target):
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE sent_danmaku (dmid VARCHAR PRIMARY KEY, cid INTEGER, bvid VARCHAR, "
            "msg TEXT, progress INTEGER, mode INTEGER, fontsize INTEGER, color INTEGER, "
            "ctime REAL, is_visible INTEGER, status INTEGER)"
        )
        conn.execute(
            "INSERT INTO sent_danmaku VALUES ('dm1', 1001, 'BV1', 'x', 0, 1, 25, 16777215, 0.0, 1, 0)"
        )
        conn.commit()
        conn.close()

        hm = HistoryManager(db_path)
        HistoryManager(db_path)   # 重复初始化不得报错

        # 迁移后的列与索引
        columns = {col.name for col in SentDanmaku._meta.database.get_columns('sent_danmaku')}
        assert 'task_id' in columns
        indexed = [
            list(index.columns)
            for index in SentDanmaku._meta.database.get_indexes('sent_danmaku')
        ]
        assert ['task_id'] in indexed

        # 老行留 NULL，新行能写能读且归属正确
        old_rows = SentDanmaku.select().order_by(SentDanmaku.dmid).execute()
        assert [r.dmid for r in old_rows] == ['dm1']
        assert old_rows[0].task_id is None

        hm.record_danmaku('任务归属-8f3c', target, Danmaku(msg='y', progress=0), 'dm2')
        new_row = SentDanmaku.get(SentDanmaku.dmid == 'dm2')
        assert new_row.task_id == '任务归属-8f3c'

    def test_migration_stamps_schema_version(self, tmp_path):
        """老库升级后打上当前数据库结构版本。"""
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE sent_danmaku (dmid VARCHAR PRIMARY KEY, cid INTEGER, bvid VARCHAR, "
            "msg TEXT, progress INTEGER, mode INTEGER, fontsize INTEGER, color INTEGER, "
            "ctime REAL, is_visible INTEGER, status INTEGER)"
        )
        conn.commit()
        conn.close()

        HistoryManager(db_path)

        version = sqlite3.connect(db_path).execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_fresh_db_stamped_without_running_migrations(self, tmp_path):
        """新库直接落成当前结构并打上最新版本，不走迁移。"""
        db_path = tmp_path / "fresh.db"

        HistoryManager(db_path)

        version = sqlite3.connect(db_path).execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_reinit_keeps_schema_version(self, tmp_path):
        """重复初始化不改写数据库结构版本。"""
        db_path = tmp_path / "fresh.db"
        HistoryManager(db_path)

        HistoryManager(db_path)

        version = sqlite3.connect(db_path).execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_future_schema_version_is_rejected(self, tmp_path):
        """数据库结构版本高于本应用支持值时报错并提示升级应用。"""
        db_path = tmp_path / "future.db"
        HistoryManager(db_path)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA user_version = 99")
        conn.commit()
        conn.close()

        with pytest.raises(RuntimeError, match="新于本应用支持的"):
            HistoryManager(db_path)
