"""SendPlan 发送计划测试 — 查重判定、爆发编排、断点前缀语义"""

import pytest

from danmaku_sender.config import SenderConfig
from danmaku_sender.service.sender.planner import PlanAction, SendPlan
from danmaku_sender.types.models.danmaku import Danmaku


def make_dms(*msgs: str) -> list[Danmaku]:
    return [Danmaku(msg=m, progress=1000 + i) for i, m in enumerate(msgs)]


def fingerprint(dm: Danmaku):
    return (dm.msg, dm.progress, dm.mode, dm.fontsize, dm.color)


def burst_config(burst_size: int = 2):
    return SenderConfig.PacingConfig(
        min_delay=8.0, max_delay=8.5,
        burst_enabled=True, burst_size=burst_size,
        rest_min=40.0, rest_max=45.0,
    ).to_task_config()


def build(dms, *, start_index=0, allow_duplicates=False, db_counts=None):
    return SendPlan(dms, start_index, burst_config(), allow_duplicates, db_counts or {})


class TestBuildPlan:
    def test_burst_rest_on_every_nth_wait(self, monkeypatch):
        """爆发休息落在第 burst_size 个等待上，最后一项不等待"""
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        plan = build(make_dms("a", "b", "c", "d"))

        assert [s.action for s in plan.steps] == [PlanAction.SEND] * 4
        assert [s.is_burst_rest for s in plan.steps] == [False, True, False, False]
        assert [s.delay for s in plan.steps] == [8.5, 45.0, 8.5, 0.0]

    def test_duplicate_is_free_step(self, monkeypatch):
        """查重跳过的计划步没有等待，也没有休息标记"""
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        dms = make_dms("a", "b")
        plan = build(dms, db_counts={fingerprint(dms[0]): 1})

        assert plan.steps[0].action is PlanAction.SKIP_DUPLICATE
        assert plan.steps[0].delay == 0.0
        assert not plan.steps[0].is_burst_rest
        assert plan.steps[1].action is PlanAction.SEND

    def test_skip_does_not_advance_burst_phase(self, monkeypatch):
        """跳过不计入爆发相位：休息落在第 N 个真发之后，而不是第 N 个条目之后"""
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        dms = make_dms("a", "b", "c", "d")
        plan = build(dms, db_counts={fingerprint(dms[0]): 1})

        assert [s.is_burst_rest for s in plan.steps] == [False, False, True, False]

    def test_occurrence_counting_within_list(self, monkeypatch):
        """同款多条按出现次数对照账本：账本有 1 条时只跳过第一条"""
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        dms = [Danmaku(msg="same", progress=1000) for _ in range(3)]
        plan = build(dms, db_counts={fingerprint(dms[0]): 1})

        assert [s.action for s in plan.steps] == [
            PlanAction.SKIP_DUPLICATE,
            PlanAction.SEND,
            PlanAction.SEND,
        ]

    def test_resume_prefix_seeds_occurrence(self, monkeypatch):
        """断点之前的同款也计入出现次数，断点之后的重复不会被误判为已发而跳过"""
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        first = Danmaku(msg="same", progress=1000)
        second = Danmaku(msg="same", progress=1000)
        dms = [first, Danmaku(msg="x", progress=2000), second]
        plan = build(dms, start_index=1, db_counts={fingerprint(first): 1})

        assert [s.index for s in plan.steps] == [1, 2]
        assert [s.action for s in plan.steps] == [PlanAction.SEND, PlanAction.SEND]

    def test_start_index_limits_steps(self):
        """起点之前的条目只参与出现次数统计，不生成计划步"""
        plan = build(make_dms("a", "b", "c"), start_index=2)
        assert [s.index for s in plan.steps] == [2]

    def test_start_index_beyond_end_is_empty(self):
        assert build(make_dms("a", "b"), start_index=99).steps == ()

    def test_allow_duplicates_sends_everything(self, monkeypatch):
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        dms = make_dms("a", "a")
        plan = build(dms, allow_duplicates=True, db_counts={fingerprint(dms[0]): 5})

        assert [s.action for s in plan.steps] == [PlanAction.SEND, PlanAction.SEND]

    def test_last_item_never_waits(self, monkeypatch):
        """最后一项发送完毕即完成，不产生等待"""
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        plan = build(make_dms("a"))
        assert plan.steps[0].delay == 0.0

    def test_last_send_waits_nothing_even_with_trailing_skips(self, monkeypatch):
        """最后一个发送步之后只剩跳过项时，它的等待归零"""
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        dms = make_dms("a", "b", "c")
        plan = build(dms, db_counts={fingerprint(dms[2]): 1})

        assert plan.steps[0].action is PlanAction.SEND
        assert plan.steps[0].delay == 8.5
        assert plan.steps[1].action is PlanAction.SEND
        assert plan.steps[1].delay == 0.0
        assert not plan.steps[1].is_burst_rest
        assert plan.steps[2].action is PlanAction.SKIP_DUPLICATE


class TestRemainingEta:
    def test_eta_is_sum_of_planned_delays(self, monkeypatch):
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        plan = build(make_dms("a", "b", "c", "d"))
        assert plan.remaining_eta() == pytest.approx(8.5 + 45.0 + 8.5 + 0.0)

    def test_eta_of_remaining_suffix(self, monkeypatch):
        """按绝对下标起算，剩余随时可算；与续传后的下标同一尺度"""
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        plan = build(make_dms("a", "b", "c", "d"))
        assert plan.remaining_eta(from_index=2) == pytest.approx(8.5)

    def test_eta_from_index_matches_absolute_scale(self, monkeypatch):
        """续传后的计划步下标是绝对位置，起算参数与之同尺度"""
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        plan = build(make_dms("a", "b", "c", "d", "e", "f"), start_index=3)

        assert [s.index for s in plan.steps] == [3, 4, 5]
        # 第 4 格是爆发休息（45），最后一项不等待
        assert plan.remaining_eta(from_index=4) == pytest.approx(45.0)
