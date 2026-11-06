"""任务时间树节点构建：分层、空节点不建、分组合计与取任务。"""
from datetime import datetime

from danmaku_sender.types.models.common import MonitorStats, TaskRecordRow
from danmaku_sender.ui.framework.tree_model import ROLE_DEPTH, TreeNode, TreeRowsModel
from danmaku_sender.ui.views.history.tree import TaskTreeBuilder


def _local(year: int, month: int, day: int, hour: int = 9) -> datetime:
    """构造本地时刻，写进任务记录的 created_at。"""
    # 树按本地日历日分组，时刻必须是不带时区的本地时间。
    return datetime(year, month, day, hour)  # noqa: DTZ001


def _record(
    task_id: str,
    created_at: datetime,
    bvid: str = "BV1xx",
    part_page: int | None = 2,
    part_title: str = "分P",
    video_title: str = "标题",
) -> TaskRecordRow:
    return TaskRecordRow(
        task_id=task_id,
        bvid=bvid,
        cid=1001,
        video_title=video_title,
        part_page=part_page,
        part_title=part_title,
        xml_path=None,
        created_at=created_at.timestamp(),
        status="COMPLETED",
    )


def _stats(
    total: int = 0,
    verified: int = 0,
    pending: int = 0,
    lost: int = 0,
) -> MonitorStats:
    return MonitorStats(total=total, verified=verified, pending=pending, lost=lost)


def _rows(tasks: list[TaskRecordRow], stats: dict[str, MonitorStats]) -> TreeRowsModel:
    """构建节点树并装载进平铺行模型。"""
    model = TreeRowsModel(("label", "sublabel", "sent", "rate", "rateTone"))
    model.set_roots(TaskTreeBuilder.build(tasks, stats))
    return model


def _value(model: TreeRowsModel, row: int, name: str):
    """按内容角色名取行取值。"""
    role = next(r for r, n in model.roleNames().items() if n.decode() == name)
    return model.data(model.index(row), role)


def _visible_labels(model: TreeRowsModel) -> list[tuple[int, str]]:
    """展开全部后取 (层深, 显示名) 序列。"""
    model.expand_all()
    return [(model.data(model.index(row), ROLE_DEPTH), _value(model, row, "label")) for row in range(model.rowCount())]


class TestTaskTree:
    """年→月→日→任务 四层；年/月/日只展开，任务是叶子"""

    def test_builds_year_month_day_task_levels(self, qapp):
        model = _rows([_record("t1", _local(2026, 10, 27))], {})

        assert _visible_labels(model) == [
            (0, "2026 年"),
            (1, "10 月"),
            (2, "27 日"),
            (3, "标题"),
        ]

    def test_skips_empty_periods(self, qapp):
        """没有任务的年/月/日不建节点"""
        model = _rows(
            [
                _record("t1", _local(2025, 3, 5)),
                _record("t2", _local(2026, 10, 27)),
                _record("t3", _local(2026, 12, 1)),
            ],
            {},
        )

        assert model.rowCount() == 2
        labels = [label for _, label in _visible_labels(model)]
        assert labels == [
            "2025 年", "3 月", "5 日", "标题",
            "2026 年", "10 月", "27 日", "标题", "12 月", "1 日", "标题",
        ]

    def test_group_totals_roll_up(self, qapp):
        """分组节点的统计是其下任务的合计"""
        model = _rows(
            [
                _record("t1", _local(2026, 10, 27)),
                _record("t2", _local(2026, 10, 27, 10)),
            ],
            {
                "t1": _stats(total=3, verified=2, pending=1),
                "t2": _stats(total=2, verified=1, lost=1),
            },
        )
        model.expand_all()

        for row in (0, 1, 2):
            assert _value(model, row, "sent") == "5"
            assert _value(model, row, "rate") == "60%"

    def test_rate_shows_dash_without_evidence(self, qapp):
        model = _rows([_record("t1", _local(2026, 10, 27))], {})
        model.expand_all()

        assert _value(model, 3, "sent") == "0"
        assert _value(model, 3, "rate") == "-"
        assert _value(model, 3, "rateTone") is None

    def test_rate_tone_follows_health(self, qapp):
        """存活率 ≥95% good、≥80% warn、其余 bad"""
        model = _rows(
            [
                _record("t1", _local(2026, 10, 27)),
                _record("t2", _local(2026, 10, 27, 10)),
                _record("t3", _local(2026, 10, 27, 11)),
            ],
            {
                "t1": _stats(total=20, verified=19),
                "t2": _stats(total=20, verified=16),
                "t3": _stats(total=20, verified=10),
            },
        )
        model.expand_all()

        for row, tone in ((3, "good"), (4, "warn"), (5, "bad")):
            assert _value(model, row, "rateTone") == tone

    def test_label_falls_back_to_bvid_without_video_title(self, qapp):
        model = _rows([_record("t1", _local(2026, 10, 27), video_title="")], {})
        model.expand_all()

        assert _value(model, 3, "label") == "BV1xx"

    def test_task_labels_split_title_and_part(self, qapp):
        """主行 = 视频标题，次行 = 分P序号 + 分P标题；与主行重复的分P标题剔除"""
        model = _rows(
            [
                _record("t1", _local(2026, 10, 27), part_title="第001集"),
                _record("t2", _local(2026, 10, 27, 10), part_title="标题"),
            ],
            {},
        )
        model.expand_all()

        assert (_value(model, 3, "label"), _value(model, 3, "sublabel")) == ("标题", "P2  第001集")
        assert (_value(model, 4, "label"), _value(model, 4, "sublabel")) == ("标题", "P2")

    def test_sublabel_omits_page_when_unspecified(self, qapp):
        model = _rows([_record("t1", _local(2026, 10, 27), part_page=None)], {})
        model.expand_all()

        assert _value(model, 3, "sublabel") == "分P"

    def test_payload_returns_record_and_stats_only_for_tasks(self, qapp):
        record = _record("t1", _local(2026, 10, 27))
        stats = {"t1": _stats(total=3, verified=2, pending=1)}
        model = _rows([record], stats)
        model.expand_all()

        assert model.payload_at(0) is None
        assert model.payload_at(2) is None
        payload = model.payload_at(3)
        assert payload == (record, stats["t1"])


def test_builder_returns_typed_nodes(qapp):
    """构建结果是 TreeNode 列表，分组节点无负载。"""
    roots = TaskTreeBuilder.build([_record("t1", _local(2026, 10, 27))], {})
    assert isinstance(roots, list) and isinstance(roots[0], TreeNode)
    assert roots[0].payload is None
