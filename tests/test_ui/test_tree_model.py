"""通用树平铺行模型：展开/折叠的行插删与角色。"""
from danmaku_sender.ui.framework.tree_model import (
    ROLE_CONTENT_BASE,
    ROLE_DEPTH,
    ROLE_EXPANDABLE,
    ROLE_EXPANDED,
    TreeNode,
    TreeRowsModel,
)


def _model() -> TreeRowsModel:
    """构造一棵 年→月→任务 三层的行模型。"""
    model = TreeRowsModel(("label",))
    year = TreeNode(
        data={"label": "2026 年"},
        children=[
            TreeNode(
                data={"label": "10 月"},
                children=[
                    TreeNode(data={"label": "任务一"}, payload="t1"),
                    TreeNode(data={"label": "任务二"}, payload="t2"),
                ],
            )
        ],
    )
    model.set_roots([year])
    return model


class TestTreeNode:
    def test_add_child_detaches_from_previous_parent(self):
        first = TreeNode(data={"label": "A"})
        second = TreeNode(data={"label": "B"})
        child = TreeNode(data={"label": "C"})
        first.add_child(child)
        second.add_child(child)
        assert first.children == []
        assert child.parent is second

    def test_add_child_same_parent_is_idempotent(self):
        parent = TreeNode()
        child = TreeNode()
        parent.add_child(child)
        parent.add_child(child)
        assert parent.children == [child]

    def test_children_constructor_detaches_from_previous_parent(self):
        child = TreeNode()
        old = TreeNode(children=[child])
        new = TreeNode(children=[child])
        assert old.children == []
        assert child.parent is new


class TestTreeRows:
    def test_collapsed_shows_roots_only(self, qapp):
        model = _model()
        assert model.rowCount() == 1
        assert model.data(model.index(0), ROLE_DEPTH) == 0
        assert model.data(model.index(0), ROLE_EXPANDABLE) is True
        assert model.data(model.index(0), ROLE_EXPANDED) is False

    def test_toggle_expands_and_collapses_rows(self, qapp):
        model = _model()
        model.toggle(0)
        assert model.rowCount() == 2
        assert model.data(model.index(1), ROLE_DEPTH) == 1

        model.toggle(1)
        assert model.rowCount() == 4
        assert [model.payload_at(row) for row in range(4)] == [None, None, "t1", "t2"]

        model.toggle(1)
        assert model.rowCount() == 2
        assert model.payload_at(1) is None

    def test_collapse_keeps_nested_expansion_state(self, qapp):
        """折叠再展开，子层的展开态保留。"""
        model = _model()
        model.toggle(0)
        model.toggle(1)
        assert model.rowCount() == 4

        model.toggle(0)
        assert model.rowCount() == 1
        model.toggle(0)
        assert model.rowCount() == 4

    def test_toggle_leaf_row_is_noop(self, qapp):
        model = _model()
        model.expand_all()
        rows = model.rowCount()
        model.toggle(2)
        assert model.rowCount() == rows

    def test_content_roles_read_node_data(self, qapp):
        model = _model()
        assert model.data(model.index(0), ROLE_CONTENT_BASE) == "2026 年"
        assert model.data(model.index(0), ROLE_EXPANDED) is False
        model.toggle(0)
        assert model.data(model.index(0), ROLE_EXPANDED) is True

    def test_payload_at_rejects_out_of_range(self, qapp):
        model = _model()
        assert model.payload_at(99) is None

    def test_set_roots_detaches_promoted_root(self, qapp):
        """把现有后代提升为根节点时，旧父的子列表不再保留它。"""
        child = TreeNode(data={"label": "子"})
        old_parent = TreeNode(children=[child])
        model = TreeRowsModel(("label",))
        model.set_roots([child])
        assert old_parent.children == []
        assert child.parent is None

    def test_data_rejects_stale_index(self, qapp):
        """模型重建后遗留的旧索引返回 None，不抛 IndexError。"""
        model = _model()
        model.expand_all()
        stale = model.index(3, 0)
        model.set_roots([])
        assert stale.isValid()
        assert model.data(stale, ROLE_CONTENT_BASE) is None
