"""历史页任务时间树的节点构建：按开始时间分 年→月→日→任务。

年/月/日只负责展开，任务是叶子。空的年/月/日不建节点。
分组节点的存活合计是其下任务的合计。
"""
from datetime import datetime
from typing import Any

from danmaku_sender.types.models.common import MonitorStats, TaskRecordRow
from danmaku_sender.ui.framework.tree_model import TreeNode


class TaskTreeBuilder:
    """把任务记录行与存活统计构建成时间树节点。

    节点 data 携带内容列 label / sublabel / sent / rate / rateTone；
    任务叶子的 payload 是 (任务记录行, 存活统计)，分组节点的 payload 为 None。

    Typical usage example::

        roots = TaskTreeBuilder.build(tasks, stats)
        tree_rows.set_roots(roots)
    """

    @staticmethod
    def build(
        tasks: list[TaskRecordRow],
        stats: dict[str, MonitorStats],
    ) -> list[TreeNode]:
        """构建 年→月→日→任务 四层节点树。

        Args:
            tasks (list[TaskRecordRow]): 任务记录行，按开始时间升序。
            stats (dict[str, MonitorStats]): 任务标识到存活统计的映射。

        Returns:
            list[TreeNode]: 年节点列表，按年份升序。
        """
        roots: list[TreeNode] = []
        years: dict[Any, TreeNode] = {}
        months: dict[Any, TreeNode] = {}
        days: dict[Any, TreeNode] = {}

        for record in tasks:
            when = datetime.fromtimestamp(record['created_at'])
            year_node = TaskTreeBuilder._group(
                years, when.year, None, roots, f"{when.year} 年"
            )
            month_node = TaskTreeBuilder._group(
                months, (when.year, when.month), year_node, roots, f"{when.month} 月"
            )
            day_node = TaskTreeBuilder._group(
                days,
                (when.year, when.month, when.day),
                month_node,
                roots,
                f"{when.day} 日",
            )

            task_stats = TaskTreeBuilder._copy_stats(stats.get(record['task_id']))
            label, sublabel = TaskTreeBuilder.task_labels(record)
            day_node.add_child(
                TreeNode(
                    data={"label": label, "sublabel": sublabel},
                    payload=(record, task_stats),
                )
            )

        for root in roots:
            TaskTreeBuilder._fill_stats(root)
        return roots

    @classmethod
    def _fill_stats(cls, node: TreeNode) -> MonitorStats:
        """汇总节点的存活合计并回填 sent / rate 列值。

        Args:
            node (TreeNode): 待回填的节点。

        Returns:
            MonitorStats: 本节点的存活合计。
        """
        if node.payload is not None:
            merged = cls._copy_stats(node.payload[1])
        else:
            merged = MonitorStats(total=0, verified=0, pending=0, lost=0)
            for child in node.children:
                sub = cls._fill_stats(child)
                merged['total'] += sub['total']
                merged['verified'] += sub['verified']
                merged['pending'] += sub['pending']
                merged['lost'] += sub['lost']

        node.data['sent'] = str(merged['total'])
        node.data['rate'] = f"{merged['verified'] / merged['total']:.0%}" if merged['total'] > 0 else "-"
        node.data['rateTone'] = TaskTreeBuilder._rate_tone(merged['verified'], merged['total'])
        return merged

    @staticmethod
    def _rate_tone(verified: int, total: int) -> str | None:
        """返回存活率的健康档位。

        Args:
            verified (int): 已存求数。
            total (int): 已发送数。

        Returns:
            str | None: 存活率 ≥95% 为 good、≥80% 为 warn、其余为 bad；无总量为 None（走中性标签）。
        """
        if total <= 0:
            return None
        ratio = verified / total
        if ratio >= 0.95:
            return "good"
        if ratio >= 0.8:
            return "warn"
        return "bad"

    @staticmethod
    def task_labels(record: TaskRecordRow) -> tuple[str, str]:
        """生成任务叶子的主行与次行显示名。

        Args:
            record (TaskRecordRow): 任务记录行。

        Returns:
            tuple[str, str]: 主行为视频标题（无标题时回落 BV 号）；次行为分P序号与分P标题，
                分P标题与主行重复时只留序号，全空时次行为空串。
        """
        label = record['video_title'] or record['bvid']
        page = f"P{record['part_page']}" if record['part_page'] is not None else ""
        part = record['part_title'] or ""
        if part == label:
            part = ""
        return label, "  ".join(filter(None, (page, part)))

    @staticmethod
    def _copy_stats(stats: MonitorStats | None) -> MonitorStats:
        """复制存活统计，未传参时返回零值。

        Args:
            stats (MonitorStats | None): 存活统计；None 表示无统计。

        Returns:
            MonitorStats: 存活统计副本。
        """
        source = stats if stats is not None else MonitorStats(
            total=0, verified=0, pending=0, lost=0
        )
        return MonitorStats(
            total=source['total'],
            verified=source['verified'],
            pending=source['pending'],
            lost=source['lost'],
        )

    @staticmethod
    def _group(
        buckets: dict[Any, TreeNode],
        key: Any,
        parent: TreeNode | None,
        roots: list[TreeNode],
        label: str,
    ) -> TreeNode:
        """取或建一个分组节点。

        Args:
            buckets (dict[Any, TreeNode]): 该层级已建节点的登记表。
            key (Any): 分组键。
            parent (TreeNode | None): 父节点，年节点为 None。
            roots (list[TreeNode]): 根列表，仅年节点挂载于此。
            label (str): 节点显示名。

        Returns:
            TreeNode: 该分组对应的节点。
        """
        node = buckets.get(key)
        if node is None:
            node = TreeNode(data={"label": label})
            if parent is None:
                roots.append(node)
            else:
                parent.add_child(node)
            buckets[key] = node
        return node
